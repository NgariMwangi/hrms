"""Dashboard and homepage."""
from datetime import date, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.overtime import OvertimeRequest
from app.models.payroll import PayrollRun, PayrollItem
from app.utils.tenant import require_company_id
from app.utils.navigation import is_employee_self_service_user, redirect_to_user_home

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """Main dashboard - show widgets based on role."""
    if is_employee_self_service_user():
        return redirect_to_user_home()
    today = date.today()
    if current_user.company_id is None:
        if current_user.is_superuser:
            flash(
                'Your account is not linked to a company yet. Create or select a company first.',
                'warning',
            )
            return redirect(url_for('settings.companies_new'))
        flash('Your account is not linked to a company. Contact your administrator.', 'danger')
        return redirect(url_for('auth.logout'))
    cid = require_company_id()
    # Headcount
    total_employees = (
        db.session.query(Employee)
        .filter(Employee.status == 'active', Employee.company_id == cid)
        .count()
    )
    # Pending leave (for managers/HR)
    pending_leave = 0
    if current_user.has_permission('approve_leave'):
        pending_leave = (
            db.session.query(LeaveRequest)
            .join(Employee, LeaveRequest.employee_id == Employee.id)
            .filter(LeaveRequest.status == 'pending', Employee.company_id == cid)
            .count()
        )
    pending_overtime = 0
    if current_user.has_permission('approve_overtime'):
        pending_overtime = (
            db.session.query(OvertimeRequest)
            .filter(
                OvertimeRequest.company_id == cid,
                OvertimeRequest.status == 'pending',
            )
            .count()
        )
    elif current_user.employee_id:
        pending_overtime = (
            db.session.query(OvertimeRequest)
            .join(Employee, OvertimeRequest.employee_id == Employee.id)
            .filter(
                OvertimeRequest.company_id == cid,
                OvertimeRequest.status == 'pending',
                Employee.manager_id == current_user.employee_id,
            )
            .count()
        )

    probation_alert_window_days = 14
    probation_nearing = []
    probation_arrived = []
    contract_alert_window_days = 60
    contract_nearing = []
    contract_arrived = []
    if current_user.has_permission('edit_employees'):
        probation_rows = (
            db.session.query(Employee)
            .filter(
                Employee.company_id == cid,
                Employee.status == 'active',
                Employee.probation_end_date.isnot(None),
            )
            .all()
        )
        for emp in probation_rows:
            end_date = emp.probation_end_date
            days_to_end = (end_date - today).days
            if 1 <= days_to_end <= probation_alert_window_days:
                probation_nearing.append(
                    {
                        'employee': emp,
                        'probation_end_date': end_date,
                        'days_to_end': days_to_end,
                    }
                )
            elif days_to_end <= 0:
                probation_arrived.append(
                    {
                        'employee': emp,
                        'probation_end_date': end_date,
                        'days_to_end': days_to_end,
                    }
                )
        probation_nearing.sort(key=lambda item: (item['days_to_end'], item['employee'].full_name.lower()))
        probation_arrived.sort(key=lambda item: (item['days_to_end'], item['employee'].full_name.lower()))

        contract_rows = (
            db.session.query(Employee)
            .filter(
                Employee.company_id == cid,
                Employee.status == 'active',
                Employee.employment_type == 'contract',
                Employee.contract_end_date.isnot(None),
            )
            .all()
        )
        for emp in contract_rows:
            end_date = emp.contract_end_date
            days_to_end = (end_date - today).days
            if 1 <= days_to_end <= contract_alert_window_days:
                contract_nearing.append(
                    {
                        'employee': emp,
                        'contract_end_date': end_date,
                        'days_to_end': days_to_end,
                    }
                )
            elif days_to_end <= 0:
                contract_arrived.append(
                    {
                        'employee': emp,
                        'contract_end_date': end_date,
                        'days_to_end': days_to_end,
                    }
                )
        contract_nearing.sort(key=lambda item: (item['days_to_end'], item['employee'].full_name.lower()))
        contract_arrived.sort(key=lambda item: (item['days_to_end'], item['employee'].full_name.lower()))

    # Upcoming birthdays (admins / HR users with employee visibility)
    birthday_window_days = 14
    upcoming_birthdays = []
    if current_user.has_permission('view_employees'):
        employees_with_birthdays = (
            db.session.query(Employee)
            .filter(
                Employee.status == 'active',
                Employee.company_id == cid,
                Employee.date_of_birth.isnot(None),
            )
            .all()
        )
        birthday_rows = []
        for emp in employees_with_birthdays:
            dob = emp.date_of_birth
            try:
                next_birthday = date(today.year, dob.month, dob.day)
            except ValueError:
                # Handle Feb 29 birthdays on non-leap years.
                next_birthday = date(today.year, 3, 1)
            if next_birthday < today:
                try:
                    next_birthday = date(today.year + 1, dob.month, dob.day)
                except ValueError:
                    next_birthday = date(today.year + 1, 3, 1)
            birthday_rows.append(
                {
                    'employee': emp,
                    'birthday': next_birthday,
                    'weekday': next_birthday.strftime('%A'),
                    'days_away': (next_birthday - today).days,
                    'coming_weekday_label': (
                        f"This coming {next_birthday.strftime('%A')}"
                        if 2 <= (next_birthday - today).days <= 6
                        else None
                    ),
                    'turning_age': next_birthday.year - dob.year,
                }
            )
        birthday_rows = [item for item in birthday_rows if item['days_away'] <= birthday_window_days]
        birthday_rows.sort(key=lambda item: (item['days_away'], item['employee'].full_name.lower()))
        upcoming_birthdays = birthday_rows
    # Recent payroll
    latest_payroll = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.company_id == cid)
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .first()
    )
    executive_summary = None
    if current_user.has_permission('view_reports') or current_user.has_permission('approve_payroll'):
        start_of_month = date(today.year, today.month, 1)
        latest_paid_or_approved = (
            db.session.query(PayrollRun)
            .filter(
                PayrollRun.company_id == cid,
                PayrollRun.status.in_(('approved', 'paid')),
            )
            .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc(), PayrollRun.id.desc())
            .first()
        )
        payroll_totals = {
            'gross': 0,
            'net': 0,
            'employees_paid': 0,
            'period': None,
        }
        if latest_paid_or_approved:
            gross_sum, net_sum, emp_count = (
                db.session.query(
                    func.coalesce(func.sum(PayrollItem.gross_pay), 0),
                    func.coalesce(func.sum(PayrollItem.net_pay), 0),
                    func.count(PayrollItem.id),
                )
                .filter(PayrollItem.payroll_run_id == latest_paid_or_approved.id)
                .one()
            )
            payroll_totals = {
                'gross': gross_sum,
                'net': net_sum,
                'employees_paid': emp_count,
                'period': f"{latest_paid_or_approved.pay_month}/{latest_paid_or_approved.pay_year}",
            }
        executive_summary = {
            'active_employees': total_employees,
            'pending_leave': pending_leave,
            'pending_overtime': pending_overtime,
            'new_hires_this_month': db.session.query(Employee).filter(
                Employee.company_id == cid,
                Employee.hire_date >= start_of_month,
            ).count(),
            'exits_this_month': db.session.query(Employee).filter(
                Employee.company_id == cid,
                Employee.termination_date.isnot(None),
                Employee.termination_date >= start_of_month,
            ).count(),
            'payroll_totals': payroll_totals,
        }
    return render_template(
        'dashboard/index.html',
        total_employees=total_employees,
        pending_leave=pending_leave,
        pending_overtime=pending_overtime,
        latest_payroll=latest_payroll,
        executive_summary=executive_summary,
        probation_alert_window_days=probation_alert_window_days,
        probation_nearing=probation_nearing,
        probation_arrived=probation_arrived,
        contract_alert_window_days=contract_alert_window_days,
        contract_nearing=contract_nearing,
        contract_arrived=contract_arrived,
        upcoming_birthdays=upcoming_birthdays,
        birthday_window_days=birthday_window_days,
    )
