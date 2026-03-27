"""
Per-employee leave entitlement statistics (used / remaining in calendar year).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveType


def normalize_gender(raw) -> str | None:
    """Return 'male', 'female', or None for unknown/other."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in ("male", "m") or s.startswith("male"):
        return "male"
    if s in ("female", "f") or s.startswith("female"):
        return "female"
    return None


def leave_types_visible_for_gender(leave_types: list, gender_key: str | None) -> list:
    """Males: hide maternity. Females: hide paternity. Other/unknown: show all."""
    out = []
    for lt in leave_types:
        code = (lt.code or "").upper()
        if gender_key == "male" and code == "MATERNITY":
            continue
        if gender_key == "female" and code == "PATERNITY":
            continue
        out.append(lt)
    return out


def _used_days_approved_in_year(employee_id: int, leave_type_id: int, year: int) -> Decimal:
    """Sum approved leave days for requests overlapping the calendar year."""
    y0 = date(year, 1, 1)
    y1 = date(year, 12, 31)
    total = (
        db.session.query(func.coalesce(func.sum(LeaveRequest.days_requested), 0))
        .filter(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.leave_type_id == leave_type_id,
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= y1,
            LeaveRequest.end_date >= y0,
        )
        .scalar()
    )
    return Decimal(str(total or 0)).quantize(Decimal("0.01"))


def statistics_for_employee(employee_id: int, year: int | None = None) -> list[dict]:
    """
    For each applicable leave type: entitlement (if any), used (YTD approved), remaining.

    Remaining = max(0, entitlement - used) when entitlement is set; otherwise remaining is None.
    """
    year = year or date.today().year
    emp = db.session.get(Employee, employee_id)
    if not emp:
        return []

    g = normalize_gender(emp.gender)
    types_q = (
        db.session.query(LeaveType)
        .filter(LeaveType.is_active.is_(True))
        .order_by(LeaveType.name)
        .all()
    )
    types_q = leave_types_visible_for_gender(types_q, g)

    rows = []
    for lt in types_q:
        used = _used_days_approved_in_year(employee_id, lt.id, year)
        ent = lt.days_per_year
        if ent is not None:
            entitlement = Decimal(str(ent)).quantize(Decimal("0.01"))
            remaining = entitlement - used
            if remaining < 0:
                remaining = Decimal("0")
        else:
            entitlement = None
            remaining = None

        rows.append(
            {
                "leave_type_id": lt.id,
                "code": lt.code,
                "name": lt.name,
                "entitlement": entitlement,
                "used": used,
                "remaining": remaining,
            }
        )
    return rows
