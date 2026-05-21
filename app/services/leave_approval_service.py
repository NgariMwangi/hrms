"""Two-step leave approval: supervisor (manager) then HR."""
from __future__ import annotations

from app.models.employee import Employee
from app.models.leave import LeaveRequest

LEAVE_STATUS_PENDING = 'pending'
LEAVE_STATUS_PENDING_HR = 'pending_hr'
LEAVE_STATUS_APPROVED = 'approved'
LEAVE_STATUS_REJECTED = 'rejected'
LEAVE_STATUS_CANCELLED = 'cancelled'

EDITABLE_STATUSES = frozenset({LEAVE_STATUS_PENDING})


def initial_leave_status_for_employee(employee: Employee | None) -> str:
    """If no manager is assigned, skip supervisor step and go straight to HR."""
    if employee and employee.manager_id:
        return LEAVE_STATUS_PENDING
    return LEAVE_STATUS_PENDING_HR


def is_supervisor_for_request(user, leave_request: LeaveRequest) -> bool:
    """True when the logged-in user is the requester's manager on the employee record."""
    if not getattr(user, 'employee_id', None):
        return False
    emp = leave_request.employee
    if not emp:
        return False
    return emp.manager_id == user.employee_id


def user_is_line_manager(user, company_id: int) -> bool:
    """True when at least one active employee lists this user as their manager."""
    if not getattr(user, 'employee_id', None):
        return False
    from app.extensions import db

    return (
        db.session.query(Employee.id)
        .filter(
            Employee.company_id == company_id,
            Employee.manager_id == user.employee_id,
            Employee.status == 'active',
        )
        .limit(1)
        .first()
        is not None
    )


def approval_stage_for_user(user, leave_request: LeaveRequest) -> str | None:
    """
    Return 'supervisor' or 'hr' if this user may act on the request now, else None.

    Supervisor step: any employee who is the requester's manager (any role, e.g. EMPLOYEE).
    HR step: users with approve_leave permission.
    """
    status = (leave_request.status or '').strip().lower()
    if getattr(user, 'is_superuser', False):
        if status in (LEAVE_STATUS_PENDING, LEAVE_STATUS_PENDING_HR):
            return 'hr'

    if status == LEAVE_STATUS_PENDING_HR and user.has_permission('approve_leave'):
        return 'hr'

    # HR may approve/reject even before the supervisor responds (supervisor unavailable).
    if status == LEAVE_STATUS_PENDING and user.has_permission('approve_leave'):
        return 'hr'

    if status == LEAVE_STATUS_PENDING and is_supervisor_for_request(user, leave_request):
        return 'supervisor'

    return None


def leave_status_label(status: str) -> str:
    labels = {
        LEAVE_STATUS_PENDING: 'Pending supervisor',
        LEAVE_STATUS_PENDING_HR: 'Pending HR',
        LEAVE_STATUS_APPROVED: 'Approved',
        LEAVE_STATUS_REJECTED: 'Rejected',
        LEAVE_STATUS_CANCELLED: 'Cancelled',
    }
    return labels.get((status or '').strip().lower(), status or '—')


def count_pending_leave_for_user(user, company_id: int) -> int:
    """Badge count: supervisor queue + HR queue for the current user."""
    from app.extensions import db
    from app.models.employee import Employee
    from app.models.leave import LeaveRequest

    total = 0
    base = (
        db.session.query(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .filter(Employee.company_id == company_id)
    )
    if getattr(user, 'employee_id', None):
        total += base.filter(
            LeaveRequest.status == LEAVE_STATUS_PENDING,
            Employee.manager_id == user.employee_id,
        ).count()
    if user.has_permission('approve_leave'):
        total += base.filter(
            LeaveRequest.status.in_((LEAVE_STATUS_PENDING, LEAVE_STATUS_PENDING_HR))
        ).count()
    return total


def supervisor_step_summary(leave_request: LeaveRequest) -> dict:
    """
    Display status of the supervisor (manager) step for HR and audit.
    Returns keys: state, label, manager_name, reviewed_at, notes, reviewer_label.
    """
    emp = leave_request.employee
    manager = emp.manager if emp else None
    manager_name = manager.full_name if manager else None

    if not emp or not emp.manager_id:
        return {
            'state': 'not_applicable',
            'label': 'No manager on file',
            'manager_name': None,
            'reviewed_at': None,
            'notes': None,
            'reviewer_label': None,
        }

    if leave_request.supervisor_reviewed_at:
        reviewer = getattr(leave_request, 'supervisor_reviewed_by', None)
        reviewer_label = None
        if reviewer and getattr(reviewer, 'email', None):
            reviewer_label = reviewer.email
        return {
            'state': 'completed',
            'label': 'Supervisor responded',
            'manager_name': manager_name,
            'reviewed_at': leave_request.supervisor_reviewed_at,
            'notes': leave_request.supervisor_notes,
            'reviewer_label': reviewer_label,
        }

    status = (leave_request.status or '').strip().lower()
    if (
        status == LEAVE_STATUS_REJECTED
        and leave_request.supervisor_reviewed_at
        and not leave_request.reviewed_at
    ):
        return {
            'state': 'rejected',
            'label': 'Rejected by supervisor',
            'manager_name': manager_name,
            'reviewed_at': leave_request.supervisor_reviewed_at,
            'notes': leave_request.supervisor_notes,
            'reviewer_label': None,
        }

    return {
        'state': 'awaiting',
        'label': 'Awaiting supervisor',
        'manager_name': manager_name,
        'reviewed_at': None,
        'notes': None,
        'reviewer_label': None,
    }


def count_all_open_leave_approvals(company_id: int) -> int:
    """Executive reports: any request not yet fully approved."""
    from app.extensions import db
    from app.models.employee import Employee
    from app.models.leave import LeaveRequest

    return (
        db.session.query(LeaveRequest)
        .join(Employee, LeaveRequest.employee_id == Employee.id)
        .filter(
            Employee.company_id == company_id,
            LeaveRequest.status.in_((LEAVE_STATUS_PENDING, LEAVE_STATUS_PENDING_HR)),
        )
        .count()
    )
