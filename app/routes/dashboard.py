"""Dashboard and homepage."""
from datetime import date

from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.payroll import PayrollRun

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """Main dashboard - show widgets based on role."""
    today = date.today()
    # Headcount
    total_employees = db.session.query(Employee).filter(Employee.status == 'active').count()
    # Pending leave (for managers/HR)
    pending_leave = 0
    if current_user.has_permission('approve_leave'):
        pending_leave = db.session.query(LeaveRequest).filter(LeaveRequest.status == 'pending').count()

    # Upcoming birthdays (admins / HR users with employee visibility)
    birthday_window_days = 14
    upcoming_birthdays = []
    if current_user.has_permission('view_employees'):
        employees_with_birthdays = (
            db.session.query(Employee)
            .filter(
                Employee.status == 'active',
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
                    'days_away': (next_birthday - today).days,
                    'turning_age': next_birthday.year - dob.year,
                }
            )
        birthday_rows = [item for item in birthday_rows if item['days_away'] <= birthday_window_days]
        birthday_rows.sort(key=lambda item: (item['days_away'], item['employee'].full_name.lower()))
        upcoming_birthdays = birthday_rows
    # Recent payroll
    latest_payroll = db.session.query(PayrollRun).order_by(
        PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc()).first()
    return render_template(
        'dashboard/index.html',
        total_employees=total_employees,
        pending_leave=pending_leave,
        latest_payroll=latest_payroll,
        upcoming_birthdays=upcoming_birthdays,
        birthday_window_days=birthday_window_days,
    )
