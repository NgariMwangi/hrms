"""Payroll processing and history."""
from decimal import Decimal
from flask import Blueprint, abort, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models.payroll import (
    PayrollRun,
    PayrollItem,
    EmployeeSalary,
    EmployeeAllowance,
    PayrollStatutoryRemittance,
    PayrollRunManualDeduction,
)
from app.models.employee import Employee as EmpModel
from app.forms.payroll_forms import PayrollRunForm, PayrollApproveForm
from app.services.payroll_engine import calculate_employee_payroll, pro_rata_factor
from app.services.deduction_service import get_manual_deduction_line_items_for_run
from app.services.statutory_remittance_service import (
    replace_statutory_remitances_for_run,
    institution_totals_for_run,
)
from app.services.audit_service import log_update, log_create, model_to_audit_dict
from app.decorators.permissions import permission_required
from datetime import date
from sqlalchemy.orm import joinedload

payroll_bp = Blueprint('payroll', __name__)

_EMPLOYEE_PAYSLIP_RUN_STATUSES = ('approved', 'paid')


@payroll_bp.route('/')
@login_required
@permission_required('view_payroll')
def index():
    runs = db.session.query(PayrollRun).order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc()).all()
    return render_template('payroll/history.html', runs=runs)


@payroll_bp.route('/run', methods=['GET', 'POST'])
@login_required
@permission_required('process_payroll')
def run():
    form = PayrollRunForm()
    if form.validate_on_submit():
        existing = db.session.query(PayrollRun).filter(
            PayrollRun.pay_month == form.pay_month.data,
            PayrollRun.pay_year == form.pay_year.data,
        ).first()
        if existing:
            flash('Payroll for this month already exists.', 'warning')
            return render_template('payroll/run_payroll.html', form=form)
        run_obj = PayrollRun(
            pay_month=form.pay_month.data,
            pay_year=form.pay_year.data,
            status='draft',
            notes=form.notes.data,
        )
        db.session.add(run_obj)
        db.session.commit()
        flash('Payroll run created. Add employees and calculate.', 'success')
        return redirect(url_for('payroll.run_calculate', id=run_obj.id))
    return render_template('payroll/run_payroll.html', form=form)


@payroll_bp.route('/run/<int:id>/calculate', methods=['GET', 'POST'])
@login_required
@permission_required('process_payroll')
def run_calculate(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.status != 'draft':
        from flask import abort
        abort(404)
    pay_date = date(run_obj.pay_year, run_obj.pay_month, 1)
    # Get active employees, then determine who is eligible (has salary for this pay date)
    employees = db.session.query(EmpModel).filter(EmpModel.status == 'active').all()
    eligible_employee_ids = set()
    missing_salary = []
    for emp in employees:
        salary = db.session.query(EmployeeSalary).filter(
            EmployeeSalary.employee_id == emp.id,
            EmployeeSalary.effective_from <= pay_date,
            (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= pay_date),
        ).order_by(EmployeeSalary.effective_from.desc()).first()
        if salary:
            eligible_employee_ids.add(emp.id)
        else:
            missing_salary.append(emp)
    eligible_count = len(eligible_employee_ids)
    if request.method == 'POST' and request.form.get('action') == 'calculate':
        # Remove existing items to avoid duplicates on recalculate
        db.session.query(PayrollItem).filter(PayrollItem.payroll_run_id == run_obj.id).delete()
        db.session.commit()
        for emp in employees:
            salary = db.session.query(EmployeeSalary).filter(
                EmployeeSalary.employee_id == emp.id,
                EmployeeSalary.effective_from <= pay_date,
                (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= pay_date),
            ).order_by(EmployeeSalary.effective_from.desc()).first()
            if not salary:
                continue
            factor = pro_rata_factor(emp.hire_date, emp.termination_date, run_obj.pay_month, run_obj.pay_year)
            # Use EmployeeAllowance table if any assignments exist for this pay date
            emp_allowances = db.session.query(EmployeeAllowance).filter(
                EmployeeAllowance.employee_id == emp.id,
                EmployeeAllowance.effective_from <= pay_date,
                (EmployeeAllowance.effective_to.is_(None)) | (EmployeeAllowance.effective_to >= pay_date),
            ).all()
            manual_lines = get_manual_deduction_line_items_for_run(run_obj.id, emp.id)
            if emp_allowances:
                allowance_breakdown = [
                    {
                        'amount': ea.amount,
                        'is_taxable': ea.allowance.is_taxable,
                        'is_pensionable': ea.allowance.is_pensionable,
                        'code': ea.allowance.code,
                        'name': ea.allowance.name,
                    }
                    for ea in emp_allowances
                ]
                calc = calculate_employee_payroll(
                    basic_salary=salary.basic_salary,
                    pension_employee_percent=salary.pension_employee_percent,
                    pay_date=pay_date,
                    pro_rata_factor=factor,
                    allowance_breakdown=allowance_breakdown,
                    employee_id=emp.id,
                    manual_deduction_lines=manual_lines,
                )
            else:
                calc = calculate_employee_payroll(
                    basic_salary=salary.basic_salary,
                    house_allowance=salary.house_allowance,
                    transport_allowance=salary.transport_allowance,
                    meal_allowance=salary.meal_allowance,
                    other_allowances=salary.other_allowances,
                    pension_employee_percent=salary.pension_employee_percent,
                    pay_date=pay_date,
                    pro_rata_factor=factor,
                    employee_id=emp.id,
                    manual_deduction_lines=manual_lines,
                )
            item = PayrollItem(
                payroll_run_id=run_obj.id,
                employee_id=emp.id,
                gross_pay=calc['gross_pay'],
                taxable_pay=calc['taxable_pay'],
                paye=calc['paye'],
                nssf_employee=calc['nssf_employee'],
                nssf_employer=calc['nssf_employer'],
                shif=calc['shif'],
                housing_levy=calc['housing_levy'],
                other_deductions=calc['other_deductions'],
                net_pay=calc['net_pay'],
                earnings_breakdown=calc['earnings_breakdown'],
                deductions_breakdown=calc['deductions_breakdown'],
                is_pro_rata=(factor < 1),
            )
            db.session.add(item)
        db.session.commit()
        flash(f'Payroll calculated for {eligible_count} employee(s).', 'success')
        return redirect(url_for('payroll.view_run', id=run_obj.id))
    return render_template(
        'payroll/run_calculate.html',
        run=run_obj,
        employees=employees,
        eligible_count=eligible_count,
        missing_salary=missing_salary,
    )


@payroll_bp.route('/run/<int:id>/manual-deductions', methods=['GET', 'POST'])
@login_required
@permission_required('process_payroll')
def run_manual_deductions(id):
    """One-off deductions for this draft payroll run (applied on next calculate)."""
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.status != 'draft':
        from flask import abort
        abort(404)
    pay_date = date(run_obj.pay_year, run_obj.pay_month, 1)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            emp_id = request.form.get('employee_id', type=int)
            label = (request.form.get('label') or '').strip()
            amount = request.form.get('amount', type=float)
            notes = (request.form.get('notes') or '').strip() or None
            if emp_id and label and amount is not None and amount > 0:
                db.session.add(
                    PayrollRunManualDeduction(
                        payroll_run_id=run_obj.id,
                        employee_id=emp_id,
                        label=label,
                        amount=Decimal(str(amount)),
                        notes=notes,
                    )
                )
                db.session.commit()
                flash('Manual deduction added. Recalculate payroll to apply.', 'success')
            else:
                flash('Select employee, label, and a positive amount.', 'danger')
        elif action == 'delete':
            mid = request.form.get('id', type=int)
            if mid:
                row = db.session.get(PayrollRunManualDeduction, mid)
                if row and row.payroll_run_id == run_obj.id:
                    db.session.delete(row)
                    db.session.commit()
                    flash('Manual deduction removed.', 'success')
        return redirect(url_for('payroll.run_manual_deductions', id=id))
    rows = (
        db.session.query(PayrollRunManualDeduction)
        .filter(PayrollRunManualDeduction.payroll_run_id == run_obj.id)
        .order_by(PayrollRunManualDeduction.id)
        .all()
    )
    employees_with_salary = []
    for emp in db.session.query(EmpModel).filter(EmpModel.status == 'active').order_by(EmpModel.first_name).all():
        sal = db.session.query(EmployeeSalary).filter(
            EmployeeSalary.employee_id == emp.id,
            EmployeeSalary.effective_from <= pay_date,
            (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= pay_date),
        ).order_by(EmployeeSalary.effective_from.desc()).first()
        if sal:
            employees_with_salary.append(emp)
    return render_template(
        'payroll/run_manual_deductions.html',
        run=run_obj,
        rows=rows,
        employees=employees_with_salary,
    )


@payroll_bp.route('/run/<int:id>')
@login_required
@permission_required('view_payroll')
def view_run(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj:
        from flask import abort
        abort(404)
    items = run_obj.items.all()
    return render_template('payroll/view_run.html', run=run_obj, items=items)


@payroll_bp.route('/run/<int:id>/approve', methods=['POST'])
@login_required
@permission_required('approve_payroll')
def approve_run(id):
    from datetime import datetime
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.status != 'draft':
        from flask import abort
        abort(404)
    run_obj.status = 'approved'
    run_obj.approved_by_id = current_user.id
    run_obj.approved_at = datetime.utcnow()
    n_lines = replace_statutory_remitances_for_run(run_obj.id)
    db.session.commit()
    log_update('PayrollRun', run_obj.id, {'status': 'draft'}, {'status': 'approved'}, user_id=current_user.id, description='Payroll approved')
    flash(
        f'Payroll approved. Statutory remittances recorded ({n_lines} line(s)) for institutions (PAYE, NSSF, SHIF, Housing).',
        'success',
    )
    return redirect(url_for('payroll.view_run', id=run_obj.id))


@payroll_bp.route('/run/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('process_payroll')
def delete_run(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj:
        flash('Payroll run not found.', 'danger')
        return redirect(url_for('payroll.index'))
    if run_obj.status != 'draft':
        flash('Only draft payrolls can be deleted. This run is already {}.'.format(run_obj.status), 'danger')
        return redirect(url_for('payroll.view_run', id=id))
    db.session.delete(run_obj)
    db.session.commit()
    flash('Payroll deleted.', 'success')
    return redirect(url_for('payroll.index'))


@payroll_bp.route('/run/<int:id>/statutory-remittances')
@login_required
@permission_required('view_payroll')
def view_statutory_remitances(id):
    """Per-employee statutory amounts owed to institutions (recorded on payroll approval)."""
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj:
        from flask import abort
        abort(404)
    if run_obj.status != 'approved':
        flash('Statutory remittances are only available after payroll is approved.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))
    remittances = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(PayrollStatutoryRemittance.payroll_run_id == run_obj.id)
        .order_by(
            PayrollStatutoryRemittance.statutory_code,
            PayrollStatutoryRemittance.employee_id,
        )
        .all()
    )
    totals = institution_totals_for_run(run_obj.id)
    grand_total = Decimal('0')
    for t in totals:
        grand_total += Decimal(str(t['total'] or 0))
    return render_template(
        'payroll/statutory_remitances.html',
        run=run_obj,
        remittances=remittances,
        totals=totals,
        grand_total=grand_total,
    )


@payroll_bp.route('/my-payslips')
@login_required
def my_payslips():
    """List finalized payslips for the logged-in user's linked employee."""
    if not current_user.employee_id:
        flash('Your account is not linked to an employee record. Contact HR.', 'warning')
        return redirect(url_for('dashboard.index'))
    emp_id = current_user.employee_id
    today_year = date.today().year
    selected_year = request.args.get('year', type=int)
    if selected_year is None:
        selected_year = today_year

    year_rows = (
        db.session.query(PayrollRun.pay_year)
        .join(PayrollItem, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollItem.employee_id == emp_id,
            PayrollRun.status.in_(_EMPLOYEE_PAYSLIP_RUN_STATUSES),
        )
        .distinct()
        .order_by(PayrollRun.pay_year.desc())
        .all()
    )
    years_from_db = [r[0] for r in year_rows]
    year_options = sorted(set(years_from_db) | {today_year}, reverse=True)

    items = (
        db.session.query(PayrollItem)
        .options(joinedload(PayrollItem.payroll_run))
        .join(PayrollRun, PayrollItem.payroll_run_id == PayrollRun.id)
        .filter(
            PayrollItem.employee_id == emp_id,
            PayrollRun.status.in_(_EMPLOYEE_PAYSLIP_RUN_STATUSES),
            PayrollRun.pay_year == selected_year,
        )
        .order_by(PayrollRun.pay_month.desc())
        .all()
    )
    return render_template(
        'payroll/my_payslips.html',
        items=items,
        selected_year=selected_year,
        year_options=year_options,
    )


@payroll_bp.route('/payslip/<int:run_id>/<int:employee_id>')
@login_required
def view_payslip(run_id, employee_id):
    from app.services.statutory_service import get_personal_relief
    item = db.session.query(PayrollItem).filter(
        PayrollItem.payroll_run_id == run_id,
        PayrollItem.employee_id == employee_id,
    ).first()
    if not item:
        abort(404)
    run = item.payroll_run
    is_own = current_user.employee_id is not None and current_user.employee_id == employee_id
    has_payroll_view = current_user.has_permission('view_payroll')
    if not is_own and not has_payroll_view:
        abort(403)
    if is_own and not has_payroll_view and run.status not in _EMPLOYEE_PAYSLIP_RUN_STATUSES:
        abort(403)
    # Breakdown helper values for display
    dd = item.deductions_breakdown or []
    nssf_tier_1 = next((d.get('amount', 0) for d in dd if d.get('code') == 'NSSF_TIER1'), 0)
    nssf_tier_2 = next((d.get('amount', 0) for d in dd if d.get('code') == 'NSSF_TIER2'), 0)
    if not nssf_tier_1 and not nssf_tier_2:
        nssf_tier_1 = float(item.nssf_employee or 0)
        nssf_tier_2 = 0
    period_date = date(item.payroll_run.pay_year, item.payroll_run.pay_month, 1)
    personal_relief = get_personal_relief(period_date)
    allowable_deductions = (item.gross_pay - item.taxable_pay)
    other_deduction_lines = []
    for d in dd:
        c = d.get('code') or ''
        if c.startswith('DED_') or c.startswith('MANUAL_') or c == 'OTHER':
            try:
                amt = float(d.get('amount') or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if amt == 0:
                continue
            other_deduction_lines.append(d)
    return render_template(
        'payroll/view_payslip.html',
        item=item,
        nssf_tier_1=nssf_tier_1,
        nssf_tier_2=nssf_tier_2,
        allowable_deductions=allowable_deductions,
        personal_relief=personal_relief,
        period_date=period_date,
        other_deduction_lines=other_deduction_lines,
    )
