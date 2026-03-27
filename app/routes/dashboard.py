"""Dashboard and homepage."""
from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.payroll import PayrollRun
from app.decorators.permissions import permission_required

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """Main dashboard - show widgets based on role."""
    # Headcount
    total_employees = db.session.query(Employee).filter(Employee.status == 'active').count()
    # Pending leave (for managers/HR)
    pending_leave = 0
    if current_user.has_permission('approve_leave'):
        pending_leave = db.session.query(LeaveRequest).filter(LeaveRequest.status == 'pending').count()
    # Recent payroll
    latest_payroll = db.session.query(PayrollRun).order_by(
        PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc()).first()
    return render_template(
        'dashboard/index.html',
        total_employees=total_employees,
        pending_leave=pending_leave,
        latest_payroll=latest_payroll,
    )
