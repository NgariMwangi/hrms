"""
Audit logging service - immutable audit trail for HRMS Kenya.
All sensitive changes MUST be logged. No updates or deletes on audit logs.
"""
from flask import request
from app.extensions import db
from app.models.audit import AuditLog


def get_client_ip():
    """Get client IP from request (handles proxies)."""
    if not request:
        return None
    return request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()


def get_user_agent():
    """Get user agent string."""
    if not request:
        return None
    ua = request.headers.get('User-Agent') or ''
    return ua[:500] if ua else None


def log_audit(
    action: str,
    record_type: str = None,
    record_id: str = None,
    old_values: dict = None,
    new_values: dict = None,
    user_id: int = None,
    description: str = None,
):
    """
    Write an immutable audit log entry.
    action: CREATE | UPDATE | DELETE | LOGIN | LOGIN_FAILED | EXPORT
    """
    entry = AuditLog(
        user_id=user_id,
        ip_address=get_client_ip(),
        user_agent=get_user_agent(),
        action=action.upper(),
        record_type=record_type,
        record_id=str(record_id) if record_id is not None else None,
        old_values=old_values,
        new_values=new_values,
        description=description,
    )
    db.session.add(entry)
    db.session.flush()  # get id if needed
    return entry


def log_create(record_type: str, record_id, new_values: dict, user_id: int = None, description: str = None):
    """Log creation of a record."""
    return log_audit(
        action='CREATE',
        record_type=record_type,
        record_id=record_id,
        new_values=new_values,
        user_id=user_id,
        description=description,
    )


def log_update(record_type: str, record_id, old_values: dict, new_values: dict, user_id: int = None, description: str = None):
    """Log update with before/after."""
    return log_audit(
        action='UPDATE',
        record_type=record_type,
        record_id=record_id,
        old_values=old_values,
        new_values=new_values,
        user_id=user_id,
        description=description,
    )


def log_delete(record_type: str, record_id, old_values: dict, user_id: int = None, description: str = None):
    """Log deletion (store last state in old_values)."""
    return log_audit(
        action='DELETE',
        record_type=record_type,
        record_id=record_id,
        old_values=old_values,
        user_id=user_id,
        description=description,
    )


def log_login(user_id: int, success: bool = True):
    """Log login attempt."""
    return log_audit(
        action='LOGIN' if success else 'LOGIN_FAILED',
        record_type='User',
        record_id=user_id,
        new_values={'success': success},
        user_id=user_id if success else None,
        description='Login successful' if success else 'Login failed',
    )


def log_export(record_type: str, description: str, user_id: int = None, extra: dict = None):
    """Log data export (e.g. payroll export)."""
    return log_audit(
        action='EXPORT',
        record_type=record_type,
        new_values=extra or {},
        user_id=user_id,
        description=description,
    )


def model_to_audit_dict(model_instance, exclude=None):
    """Convert model to dict for audit old_values/new_values (exclude sensitive)."""
    exclude = set(exclude or [])
    exclude |= {'password_hash', 'password'}
    return {
        c.name: (str(getattr(model_instance, c.name)) if hasattr(model_instance, c.name) else None)
        for c in model_instance.__table__.columns
        if c.name not in exclude
    }
