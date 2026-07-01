"""
Recurring employee deductions and per-payroll manual deduction lines.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.payroll import EmployeeDeduction, PayrollRunManualDeduction


def decimalize(value) -> Decimal:
    if value is None:
        return Decimal('0')
    return Decimal(str(value))


def pay_period_bounds(pay_date: date) -> tuple[date, date]:
    """First and last calendar day of the payroll month containing pay_date."""
    _, last_day = monthrange(pay_date.year, pay_date.month)
    period_start = date(pay_date.year, pay_date.month, 1)
    period_end = date(pay_date.year, pay_date.month, last_day)
    return period_start, period_end


def deduction_overlaps_pay_period(
    effective_from: date,
    effective_to: date | None,
    period_start: date,
    period_end: date,
) -> bool:
    if effective_from > period_end:
        return False
    if effective_to is not None and effective_to < period_start:
        return False
    return True


def _active_employee_deductions(employee_id: int, pay_date: date):
    period_start, period_end = pay_period_bounds(pay_date)
    return (
        db.session.query(EmployeeDeduction)
        .filter(
            EmployeeDeduction.employee_id == employee_id,
            EmployeeDeduction.is_active.is_(True),
            EmployeeDeduction.effective_from <= period_end,
            (EmployeeDeduction.effective_to.is_(None)) | (EmployeeDeduction.effective_to >= period_start),
        )
        .order_by(EmployeeDeduction.id)
        .all()
    )


def compute_recurring_line_amount(row: EmployeeDeduction, gross_pay: Decimal, basic_pay: Decimal) -> Decimal:
    """Compute one month's deduction for a single EmployeeDeduction row."""
    mode = (row.calculation_mode or 'fixed').lower()
    if mode == 'percent_basic':
        rate = decimalize(row.rate_percent)
        amt = (basic_pay * rate / Decimal('100')).quantize(Decimal('0.01'))
    elif mode == 'percent_gross':
        rate = decimalize(row.rate_percent)
        amt = (gross_pay * rate / Decimal('100')).quantize(Decimal('0.01'))
    else:
        amt = decimalize(row.amount).quantize(Decimal('0.01'))
    if row.remaining_balance is not None:
        bal = decimalize(row.remaining_balance)
        if bal <= 0:
            return Decimal('0')
        amt = min(amt, bal).quantize(Decimal('0.01'))
    return amt


def get_recurring_deduction_line_items(
    employee_id: int,
    pay_date: date,
    gross_pay: Decimal,
    basic_pay: Decimal,
) -> list:
    """
    Returns [{ 'code', 'name', 'amount' (Decimal) }, ...] for active recurring deductions.
    """
    gross_pay = decimalize(gross_pay).quantize(Decimal('0.01'))
    basic_pay = decimalize(basic_pay).quantize(Decimal('0.01'))
    out = []
    for row in _active_employee_deductions(employee_id, pay_date):
        amt = compute_recurring_line_amount(row, gross_pay, basic_pay)
        if amt <= 0:
            continue
        code = f"DED_{row.id}"
        name = (row.title or '').strip()
        if not name and row.deduction:
            name = row.deduction.name
        if not name:
            name = 'Deduction'
        if row.notes:
            name = f"{name} ({row.notes})"
        out.append({'code': code, 'name': name, 'amount': amt})
    return out


def get_manual_deduction_line_items_for_run(payroll_run_id: int, employee_id: int) -> list:
    """Manual one-off lines for this employee on this draft payroll run."""
    rows = (
        db.session.query(PayrollRunManualDeduction)
        .filter(
            PayrollRunManualDeduction.payroll_run_id == payroll_run_id,
            PayrollRunManualDeduction.employee_id == employee_id,
        )
        .order_by(PayrollRunManualDeduction.id)
        .all()
    )
    out = []
    for r in rows:
        amt = decimalize(r.amount).quantize(Decimal('0.01'))
        if amt <= 0:
            continue
        out.append(
            {
                'code': f"MANUAL_{r.id}",
                'name': r.label,
                'amount': amt,
            }
        )
    return out


def total_manual_for_run_employee(payroll_run_id: int, employee_id: int) -> Decimal:
    lines = get_manual_deduction_line_items_for_run(payroll_run_id, employee_id)
    return sum((x['amount'] for x in lines), start=Decimal('0')).quantize(Decimal('0.01'))
