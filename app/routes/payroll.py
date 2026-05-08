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
    PayrollRunExclusion,
)
from app.models.employee import Employee as EmpModel
from app.models.company import Branch
from app.models.overtime import OvertimeRequest
from app.models.benefit import EmployeeBenefit
from app.forms.payroll_forms import PayrollRunForm, PayrollApproveForm
from app.services.payroll_engine import calculate_employee_payroll, pro_rata_factor
from app.services.deduction_service import get_manual_deduction_line_items_for_run
from app.services.statutory_remittance_service import (
    replace_statutory_remitances_for_run,
    institution_totals_for_run,
)
from app.services.audit_service import log_update, log_create, model_to_audit_dict
from app.decorators.permissions import permission_required
from app.utils.tenant import require_company_id
from app.utils.currency import currency_for_country
from datetime import date
from sqlalchemy import update
from sqlalchemy import extract
from sqlalchemy.orm import joinedload

payroll_bp = Blueprint('payroll', __name__)

_EMPLOYEE_PAYSLIP_RUN_STATUSES = ('approved', 'finance_reviewed', 'paid')


def _cc(raw) -> str:
    return (raw or 'KE').strip().upper()[:2]


@payroll_bp.route('/')
@login_required
@permission_required('view_payroll')
def index():
    cid = require_company_id()
    country_rows = (
        db.session.query(Branch.country_code)
        .filter(Branch.company_id == cid, Branch.country_code.isnot(None))
        .distinct()
        .order_by(Branch.country_code)
        .all()
    )
    countries_nav = [_cc(cc) for (cc,) in country_rows if cc] or ['KE']
    selected_country = _cc(request.args.get('country_code') or countries_nav[0])
    if selected_country not in countries_nav:
        countries_nav.append(selected_country)
        countries_nav = sorted(set(countries_nav))
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.company_id == cid, PayrollRun.country_code == selected_country)
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    return render_template(
        'payroll/history.html',
        runs=runs,
        countries_nav=countries_nav,
        selected_country=selected_country,
    )


@payroll_bp.route('/run', methods=['GET', 'POST'])
@login_required
@permission_required('process_payroll')
def run():
    form = PayrollRunForm()
    cid = require_company_id()
    country_rows = (
        db.session.query(Branch.country_code)
        .filter(Branch.company_id == cid, Branch.country_code.isnot(None))
        .distinct()
        .order_by(Branch.country_code)
        .all()
    )
    countries = [(_cc(cc), _cc(cc)) for (cc,) in country_rows if cc]
    if not countries:
        countries = [('KE', 'KE')]
    preferred = _cc(request.args.get('country_code') or countries[0][0])
    if request.method == 'GET':
        form.country_code.data = preferred
    if form.validate_on_submit():
        cc = _cc(form.country_code.data)
        existing = db.session.query(PayrollRun).filter(
            PayrollRun.company_id == cid,
            PayrollRun.country_code == cc,
            PayrollRun.pay_month == form.pay_month.data,
            PayrollRun.pay_year == form.pay_year.data,
        ).first()
        if existing:
            flash(f'Payroll for {cc} in this month already exists.', 'warning')
            return render_template('payroll/run_payroll.html', form=form, countries=countries)
        run_obj = PayrollRun(
            company_id=cid,
            country_code=cc,
            pay_month=form.pay_month.data,
            pay_year=form.pay_year.data,
            status='draft',
            notes=form.notes.data,
        )
        db.session.add(run_obj)
        db.session.commit()
        flash(f'Payroll run ({cc}) created. Add employees and calculate.', 'success')
        return redirect(url_for('payroll.run_calculate', id=run_obj.id))
    return render_template('payroll/run_payroll.html', form=form, countries=countries)


@payroll_bp.route('/run/<int:id>/calculate', methods=['GET', 'POST'])
@login_required
@permission_required('process_payroll')
def run_calculate(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.status != 'draft' or run_obj.company_id != require_company_id():
        from flask import abort
        abort(404)
    pay_date = date(run_obj.pay_year, run_obj.pay_month, 1)
    from calendar import monthrange
    _, month_last_day = monthrange(run_obj.pay_year, run_obj.pay_month)
    period_start = date(run_obj.pay_year, run_obj.pay_month, 1)
    period_end = date(run_obj.pay_year, run_obj.pay_month, month_last_day)
    run_cc = _cc(run_obj.country_code)
    run_currency = currency_for_country(run_cc)
    # Get active employees, then determine who is eligible (has salary for this pay date)
    employees = (
        db.session.query(EmpModel)
        .options(joinedload(EmpModel.branch))
        .join(Branch, EmpModel.branch_id == Branch.id)
        .filter(
            EmpModel.company_id == run_obj.company_id,
            EmpModel.status == 'active',
            Branch.country_code == run_cc,
        )
        .all()
    )
    eligible_employee_ids = set()
    missing_salary = []
    for emp in employees:
        salary = db.session.query(EmployeeSalary).filter(
            EmployeeSalary.employee_id == emp.id,
            EmployeeSalary.effective_from <= period_end,
            (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= period_start),
        ).order_by(EmployeeSalary.effective_from.desc(), EmployeeSalary.id.desc()).first()
        if salary:
            eligible_employee_ids.add(emp.id)
        else:
            missing_salary.append(emp)
    eligible_count = len(eligible_employee_ids)
    missing_salary_ids = {e.id for e in missing_salary}
    excluded_rows = (
        db.session.query(PayrollRunExclusion)
        .filter(PayrollRunExclusion.payroll_run_id == run_obj.id)
        .all()
    )
    excluded_employee_ids = {row.employee_id for row in excluded_rows}
    excluded_count = len(excluded_employee_ids & eligible_employee_ids)
    included_count = max(eligible_count - excluded_count, 0)

    if request.method == 'POST' and request.form.get('action') == 'save_exclusions':
        selected = set(request.form.getlist('excluded_employee_ids', type=int))
        selected = {eid for eid in selected if eid in eligible_employee_ids}
        db.session.query(PayrollRunExclusion).filter(
            PayrollRunExclusion.payroll_run_id == run_obj.id
        ).delete()
        for eid in sorted(selected):
            db.session.add(PayrollRunExclusion(payroll_run_id=run_obj.id, employee_id=eid))
        db.session.commit()
        flash(f'Payroll exclusions updated ({len(selected)} employee(s) excluded).', 'success')
        return redirect(url_for('payroll.run_calculate', id=run_obj.id))

    if request.method == 'POST' and request.form.get('action') == 'calculate':
        excluded_employee_ids = {
            row.employee_id
            for row in db.session.query(PayrollRunExclusion)
            .filter(PayrollRunExclusion.payroll_run_id == run_obj.id)
            .all()
        }
        # Release overtime rows tied to this draft run, then replace line items
        db.session.execute(
            update(OvertimeRequest)
            .where(OvertimeRequest.applied_to_payroll_run_id == run_obj.id)
            .values(applied_to_payroll_run_id=None)
        )
        db.session.query(PayrollItem).filter(PayrollItem.payroll_run_id == run_obj.id).delete()
        db.session.commit()
        for emp in employees:
            if emp.id in excluded_employee_ids:
                continue
            salary = db.session.query(EmployeeSalary).filter(
                EmployeeSalary.employee_id == emp.id,
                EmployeeSalary.effective_from <= period_end,
                (EmployeeSalary.effective_to.is_(None)) | (EmployeeSalary.effective_to >= period_start),
            ).order_by(EmployeeSalary.effective_from.desc(), EmployeeSalary.id.desc()).first()
            if not salary:
                continue
            # Pro-rate using employee lifecycle and salary window overlap.
            hire_or_start = emp.hire_date
            if salary.effective_from and (not hire_or_start or salary.effective_from > hire_or_start):
                hire_or_start = salary.effective_from
            end_or_termination = emp.termination_date
            if salary.effective_to and (not end_or_termination or salary.effective_to < end_or_termination):
                end_or_termination = salary.effective_to
            if getattr(emp, 'prorate_payroll', True):
                factor = pro_rata_factor(hire_or_start, end_or_termination, run_obj.pay_month, run_obj.pay_year)
            else:
                factor = Decimal('1')
            # Use EmployeeAllowance table if any assignments exist for this pay date
            emp_allowances = db.session.query(EmployeeAllowance).filter(
                EmployeeAllowance.employee_id == emp.id,
                EmployeeAllowance.effective_from <= pay_date,
                (EmployeeAllowance.effective_to.is_(None)) | (EmployeeAllowance.effective_to >= pay_date),
            ).all()
            emp_benefits = db.session.query(EmployeeBenefit).filter(
                EmployeeBenefit.employee_id == emp.id,
                EmployeeBenefit.is_active.is_(True),
                db.or_(
                    db.and_(
                        EmployeeBenefit.payroll_year == run_obj.pay_year,
                        EmployeeBenefit.payroll_month == run_obj.pay_month,
                    ),
                    db.and_(
                        EmployeeBenefit.payroll_year.is_(None),
                        EmployeeBenefit.payroll_month.is_(None),
                        EmployeeBenefit.effective_date.isnot(None),
                        extract('year', EmployeeBenefit.effective_date) == run_obj.pay_year,
                        extract('month', EmployeeBenefit.effective_date) == run_obj.pay_month,
                    ),
                ),
            ).all()
            manual_lines = get_manual_deduction_line_items_for_run(run_obj.id, emp.id)
            ot_rows = (
                db.session.query(OvertimeRequest)
                .filter(
                    OvertimeRequest.company_id == run_obj.company_id,
                    OvertimeRequest.employee_id == emp.id,
                    OvertimeRequest.for_pay_month == run_obj.pay_month,
                    OvertimeRequest.for_pay_year == run_obj.pay_year,
                    OvertimeRequest.status == 'approved',
                    OvertimeRequest.applied_to_payroll_run_id.is_(None),
                )
                .all()
            )
            overtime_days = sum((Decimal(str(r.days)) for r in ot_rows), start=Decimal('0'))
            if emp_allowances or emp_benefits:
                allowance_breakdown = []
                if emp_allowances:
                    allowance_breakdown.extend([
                    {
                        'amount': ea.amount,
                        'is_taxable': ea.allowance.is_taxable,
                        'is_pensionable': ea.allowance.is_pensionable,
                        'code': ea.allowance.code,
                        'name': ea.allowance.name,
                    }
                    for ea in emp_allowances
                    ])
                else:
                    # Preserve legacy salary allowance behavior when no EmployeeAllowance rows exist.
                    allowance_breakdown.extend([
                        {'amount': salary.house_allowance, 'is_taxable': True, 'is_pensionable': True, 'code': 'HOUSE', 'name': 'House Allowance'},
                        {'amount': salary.transport_allowance, 'is_taxable': True, 'is_pensionable': False, 'code': 'TRANSPORT', 'name': 'Transport Allowance'},
                        {'amount': salary.meal_allowance, 'is_taxable': True, 'is_pensionable': False, 'code': 'MEAL', 'name': 'Meal Allowance'},
                        {'amount': salary.other_allowances, 'is_taxable': True, 'is_pensionable': False, 'code': 'OTHER_ALLOW', 'name': 'Other Allowances'},
                    ])
                allowance_breakdown.extend(
                    {
                        'amount': b.amount,
                        'is_taxable': False,
                        'is_pensionable': False,
                        'code': f'BEN-{b.id}',
                        'name': b.title or 'Benefit',
                    }
                    for b in emp_benefits
                )
                calc = calculate_employee_payroll(
                    basic_salary=salary.basic_salary,
                    pension_employee_percent=salary.pension_employee_percent,
                    pension_employee_fixed_amount=salary.pension_employee_fixed_amount,
                    pay_date=pay_date,
                    pro_rata_factor=factor,
                    allowance_breakdown=allowance_breakdown,
                    employee_id=emp.id,
                    manual_deduction_lines=manual_lines,
                    statutory_company_id=emp.company_id,
                    statutory_country_code=run_cc,
                    overtime_days=overtime_days,
                )
            else:
                calc = calculate_employee_payroll(
                    basic_salary=salary.basic_salary,
                    house_allowance=salary.house_allowance,
                    transport_allowance=salary.transport_allowance,
                    meal_allowance=salary.meal_allowance,
                    other_allowances=salary.other_allowances,
                    pension_employee_percent=salary.pension_employee_percent,
                    pension_employee_fixed_amount=salary.pension_employee_fixed_amount,
                    pay_date=pay_date,
                    pro_rata_factor=factor,
                    employee_id=emp.id,
                    manual_deduction_lines=manual_lines,
                    statutory_company_id=emp.company_id,
                    statutory_country_code=run_cc,
                    overtime_days=overtime_days,
                )
            for ot_r in ot_rows:
                ot_r.applied_to_payroll_run_id = run_obj.id
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
        processed = max(eligible_count - len(excluded_employee_ids & eligible_employee_ids), 0)
        flash(f'Payroll calculated for {processed} employee(s).', 'success')
        return redirect(url_for('payroll.view_run', id=run_obj.id))
    return render_template(
        'payroll/run_calculate.html',
        run=run_obj,
        run_country_code=run_cc,
        run_currency=run_currency,
        employees=employees,
        eligible_count=eligible_count,
        excluded_employee_ids=excluded_employee_ids,
        excluded_count=excluded_count,
        included_count=included_count,
        missing_salary_ids=missing_salary_ids,
        missing_salary=missing_salary,
    )


@payroll_bp.route('/run/<int:id>/manual-deductions', methods=['GET', 'POST'])
@login_required
@permission_required('process_payroll')
def run_manual_deductions(id):
    """One-off deductions for this draft payroll run (applied on next calculate)."""
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.status != 'draft' or run_obj.company_id != require_company_id():
        from flask import abort
        abort(404)
    pay_date = date(run_obj.pay_year, run_obj.pay_month, 1)
    run_cc = _cc(run_obj.country_code)
    run_currency = currency_for_country(run_cc)
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
    for emp in (
        db.session.query(EmpModel)
        .join(Branch, EmpModel.branch_id == Branch.id)
        .filter(EmpModel.company_id == run_obj.company_id, EmpModel.status == 'active')
        .filter(Branch.country_code == run_cc)
        .order_by(EmpModel.first_name)
        .all()
    ):
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
        run_country_code=run_cc,
        run_currency=run_currency,
        rows=rows,
        employees=employees_with_salary,
    )


@payroll_bp.route('/run/<int:id>')
@login_required
@permission_required('view_payroll')
def view_run(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
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
    if not run_obj or run_obj.status != 'draft' or run_obj.company_id != require_company_id():
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


@payroll_bp.route('/run/<int:id>/finance-review', methods=['POST'])
@login_required
@permission_required('review_payroll_finance')
def finance_review_run(id):
    from datetime import datetime

    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
        abort(404)
    if run_obj.status != 'approved':
        flash('Only approved payroll runs can be marked as finance reviewed.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))
    run_obj.status = 'finance_reviewed'
    run_obj.finance_reviewed_by_id = current_user.id
    run_obj.finance_reviewed_at = datetime.utcnow()
    db.session.commit()
    log_update(
        'PayrollRun',
        run_obj.id,
        {'status': 'approved'},
        {'status': 'finance_reviewed'},
        user_id=current_user.id,
        description='Payroll finance review completed',
    )
    flash('Payroll marked as finance reviewed.', 'success')
    return redirect(url_for('payroll.view_run', id=run_obj.id))


@payroll_bp.route('/run/<int:id>/mark-paid', methods=['POST'])
@login_required
@permission_required('mark_payroll_paid')
def mark_paid_run(id):
    from datetime import datetime

    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
        abort(404)
    if run_obj.status not in ('approved', 'finance_reviewed'):
        flash('Only approved/finance-reviewed payroll runs can be marked paid.', 'warning')
        return redirect(url_for('payroll.view_run', id=id))
    previous = run_obj.status
    run_obj.status = 'paid'
    run_obj.paid_by_id = current_user.id
    run_obj.paid_at = datetime.utcnow()
    payment_ref = (request.form.get('payment_reference') or '').strip()
    run_obj.payment_reference = payment_ref or None
    db.session.commit()
    log_update(
        'PayrollRun',
        run_obj.id,
        {'status': previous},
        {'status': 'paid', 'payment_reference': run_obj.payment_reference},
        user_id=current_user.id,
        description='Payroll marked as paid by finance',
    )
    flash('Payroll marked as paid.', 'success')
    return redirect(url_for('payroll.view_run', id=run_obj.id))


@payroll_bp.route('/run/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('process_payroll')
def delete_run(id):
    run_obj = db.session.get(PayrollRun, id)
    if not run_obj or run_obj.company_id != require_company_id():
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
    if not run_obj or run_obj.company_id != require_company_id():
        from flask import abort
        abort(404)
    if run_obj.status not in ('approved', 'finance_reviewed', 'paid'):
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
            PayrollRun.company_id == current_user.company_id,
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
            PayrollRun.company_id == current_user.company_id,
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
    item = (
        db.session.query(PayrollItem)
        .options(joinedload(PayrollItem.employee).joinedload(EmpModel.branch))
        .filter(
            PayrollItem.payroll_run_id == run_id,
            PayrollItem.employee_id == employee_id,
        )
        .first()
    )
    if not item:
        abort(404)
    run = item.payroll_run
    if not run or run.company_id != require_company_id():
        abort(404)
    is_own = current_user.employee_id is not None and current_user.employee_id == employee_id
    has_payroll_view = current_user.has_permission('view_payroll')
    if not is_own and not has_payroll_view:
        abort(403)
    if is_own and not has_payroll_view and run.status not in _EMPLOYEE_PAYSLIP_RUN_STATUSES:
        abort(403)
    # Breakdown helper values for country-aware payslip display
    dd = item.deductions_breakdown or []
    period_date = date(item.payroll_run.pay_year, item.payroll_run.pay_month, 1)
    emp_ps = item.employee
    scc = (emp_ps.branch.country_code if emp_ps and emp_ps.branch else 'KE').upper()[:2]
    personal_relief = get_personal_relief(period_date, emp_ps.company_id, scc) if emp_ps else Decimal('0')
    nssf_tier_1 = next((d.get('amount', 0) for d in dd if d.get('code') == 'NSSF_TIER1'), 0)
    nssf_tier_2 = next((d.get('amount', 0) for d in dd if d.get('code') == 'NSSF_TIER2'), 0)
    has_nssf_tiers = any((d.get('code') or '').startswith('NSSF_TIER') for d in dd)
    show_nssf_tiers = has_nssf_tiers and scc == 'KE'
    show_shif = Decimal(str(item.shif or 0)) > 0
    show_housing_levy = Decimal(str(item.housing_levy or 0)) > 0
    show_personal_relief = Decimal(str(personal_relief or 0)) > 0
    allowable_deductions = (item.gross_pay - item.taxable_pay)
    overtime_amount = Decimal('0')
    for e in (item.earnings_breakdown or []):
        if (e.get('code') or '').upper() != 'OVERTIME':
            continue
        try:
            overtime_amount += Decimal(str(e.get('amount') or 0))
        except Exception:
            continue
    show_overtime = overtime_amount > 0
    other_deduction_lines = []
    pension_percent_amount = Decimal('0')
    pension_fixed_amount = Decimal('0')
    for d in dd:
        c = d.get('code') or ''
        if c == 'PENSION_PERCENT':
            try:
                pension_percent_amount += Decimal(str(d.get('amount') or 0))
            except Exception:
                pass
            continue
        if c == 'PENSION_FIXED':
            try:
                pension_fixed_amount += Decimal(str(d.get('amount') or 0))
            except Exception:
                pass
            continue
        if c.startswith('DED_') or c.startswith('MANUAL_') or c == 'OTHER':
            try:
                amt = float(d.get('amount') or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if amt == 0:
                continue
            other_deduction_lines.append(d)
    from app.utils.currency import currency_for_employee

    payslip_currency = currency_for_employee(
        item.employee,
        app_default=current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    )
    return render_template(
        'payroll/view_payslip.html',
        item=item,
        nssf_tier_1=nssf_tier_1,
        nssf_tier_2=nssf_tier_2,
        allowable_deductions=allowable_deductions,
        personal_relief=personal_relief,
        period_date=period_date,
        other_deduction_lines=other_deduction_lines,
        payslip_currency=payslip_currency,
        statutory_country_code=scc,
        show_nssf_tiers=show_nssf_tiers,
        show_shif=show_shif,
        show_housing_levy=show_housing_levy,
        show_personal_relief=show_personal_relief,
        overtime_amount=overtime_amount,
        show_overtime=show_overtime,
        pension_percent_amount=pension_percent_amount,
        pension_fixed_amount=pension_fixed_amount,
    )
