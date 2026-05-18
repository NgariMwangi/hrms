"""Template context processors: permissions, config."""
from flask_login import current_user
from sqlalchemy.orm import joinedload


def register_template_filters(app):
    """Jinja filters used across templates."""
    from app.utils.formatters import format_currency, mask_bank_account

    @app.template_filter('mask_bank_account')
    def mask_bank_account_filter(number, visible=4):
        return mask_bank_account(number or '', visible=visible)

    @app.template_filter('fmt_money')
    def fmt_money(value, curr='KES'):
        return format_currency(value, curr)

    @app.template_filter('fmt_days')
    def fmt_days(value):
        """Show day counts without unnecessary decimals (21 not 21.00; 0.5 stays 0.5)."""
        if value is None:
            return ''
        try:
            f = float(value)
        except (TypeError, ValueError):
            return value
        if f != f:  # NaN
            return value
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        return '%g' % f


def inject_permissions():
    """Expose current_user and has_permission to templates."""
    from app.utils.navigation import is_employee_self_service_user, user_home_endpoint

    def has_permission(code):
        if not current_user.is_authenticated:
            return False
        return current_user.has_permission(code)

    if current_user.is_authenticated:
        ess = is_employee_self_service_user()
        home_ep = user_home_endpoint()
    else:
        ess = False
        home_ep = 'auth.login'

    return {
        'current_user': current_user,
        'has_permission': has_permission,
        'is_employee_self_service': ess,
        'home_endpoint': home_ep,
    }


def inject_config():
    """Expose app config values needed in templates."""
    from flask import current_app
    return {
        'app_name': 'HRMS Kenya',
        'currency': current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    }


def inject_tenant_nav():
    """
    Company + branch for top bar: tenant from user.company; branch from linked employee.branch
    when present. If the user is not linked to an employee, show the company's first branch
    (by name) as the organizational default so the bar is still accurate.
    """
    empty = {
        'tenant_nav': {
            'company': None,
            'branch': None,
            'currency': None,
            'branch_is_personal': None,
        },
    }
    if not current_user.is_authenticated:
        return empty
    uid = getattr(current_user, 'id', None)
    if not uid:
        return empty
    from flask import current_app
    from app.extensions import db
    from app.models.user import User
    from app.models.employee import Employee
    from app.models.company import Branch
    from app.utils.currency import currency_for_branch, currency_for_employee

    u = (
        db.session.query(User)
        .options(
            joinedload(User.company),
            joinedload(User.employee).joinedload(Employee.branch),
        )
        .filter(User.id == uid)
        .first()
    )
    if not u:
        return empty

    company_name = (u.company.name if u.company else None) or None
    branch_label = None
    branch_is_personal = None
    app_def = current_app.config.get('DEFAULT_CURRENCY', 'KES')
    payroll_currency = app_def
    if u.employee and u.employee.branch:
        br = u.employee.branch
        branch_label = f'{br.name} · {br.country_code}'
        branch_is_personal = True
        payroll_currency = currency_for_employee(
            u.employee,
            app_default=app_def,
        )
    elif u.company_id:
        br = (
            db.session.query(Branch)
            .filter(Branch.company_id == u.company_id)
            .order_by(Branch.name)
            .first()
        )
        if br:
            branch_label = f'{br.name} · {br.country_code}'
            branch_is_personal = False
            payroll_currency = currency_for_branch(br, app_default=app_def)
    return {
        'tenant_nav': {
            'company': company_name,
            'branch': branch_label,
            'currency': payroll_currency,
            'branch_is_personal': branch_is_personal,
        }
    }


def inject_pending_approvals():
    """Global pending approvals counters for top-bar notifications."""
    empty = {
        'pending_approvals': {
            'leave': 0,
            'overtime': 0,
            'total': 0,
        }
    }
    if not current_user.is_authenticated or not getattr(current_user, 'company_id', None):
        return empty

    from app.extensions import db
    from app.models.employee import Employee
    from app.models.leave import LeaveRequest
    from app.models.overtime import OvertimeRequest

    cid = current_user.company_id
    leave_pending = 0
    overtime_pending = 0

    if current_user.has_permission('approve_leave'):
        leave_pending = (
            db.session.query(LeaveRequest)
            .join(Employee, LeaveRequest.employee_id == Employee.id)
            .filter(LeaveRequest.status == 'pending', Employee.company_id == cid)
            .count()
        )

    if current_user.has_permission('approve_overtime'):
        overtime_pending = (
            db.session.query(OvertimeRequest)
            .filter(OvertimeRequest.company_id == cid, OvertimeRequest.status == 'pending')
            .count()
        )
    elif current_user.employee_id:
        overtime_pending = (
            db.session.query(OvertimeRequest)
            .join(Employee, OvertimeRequest.employee_id == Employee.id)
            .filter(
                OvertimeRequest.company_id == cid,
                OvertimeRequest.status == 'pending',
                Employee.manager_id == current_user.employee_id,
            )
            .count()
        )

    return {
        'pending_approvals': {
            'leave': leave_pending,
            'overtime': overtime_pending,
            'total': leave_pending + overtime_pending,
        }
    }
