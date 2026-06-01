"""Shared payroll helpers (earnings, proration) used by country-specific engines."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.statutory_service import get_pensionable_pay

PRORATA_STANDARD_MONTH_DAYS = 30


def decimalize(value) -> Decimal:
    if value is None:
        return Decimal('0')
    return Decimal(str(value))


def employment_partial_month_days(
    hire_date: date | None,
    termination_date: date | None,
    pay_month: int,
    pay_year: int,
) -> tuple[int, bool]:
    from calendar import monthrange

    month_start = date(pay_year, pay_month, 1)
    _, last_day = monthrange(pay_year, pay_month)
    month_end = date(pay_year, pay_month, last_day)
    work_start = month_start
    work_end = month_end
    if hire_date and hire_date > month_start:
        work_start = hire_date
    if termination_date and termination_date < month_end:
        work_end = termination_date
    if work_start > work_end:
        return 0, True
    days_worked = (work_end - work_start).days + 1
    partial_month = (work_start > month_start) or (work_end < month_end)
    return days_worked, partial_month


def pro_rata_calendar_days_or_none(
    hire_date: date | None,
    termination_date: date | None,
    pay_month: int,
    pay_year: int,
) -> int | None:
    days_worked, partial = employment_partial_month_days(
        hire_date, termination_date, pay_month, pay_year
    )
    if not partial:
        return None
    return days_worked


def pro_rata_factor(
    hire_date: date | None,
    termination_date: date | None,
    pay_month: int,
    pay_year: int,
) -> Decimal:
    days_worked, partial = employment_partial_month_days(
        hire_date, termination_date, pay_month, pay_year
    )
    if not partial:
        return Decimal('1')
    denom = Decimal(PRORATA_STANDARD_MONTH_DAYS)
    if denom <= 0:
        return Decimal('0')
    return Decimal(days_worked) / denom


def build_gross_earnings(
    *,
    basic_salary: Decimal,
    house_allowance: Decimal | None = None,
    transport_allowance: Decimal | None = None,
    meal_allowance: Decimal | None = None,
    other_allowances: Decimal | None = None,
    pro_rata_factor: Decimal | None = None,
    pro_rata_calendar_days: int | None = None,
    other_earnings: Decimal | None = None,
    allowance_breakdown: list | None = None,
    overtime_days: Decimal | None = None,
) -> tuple[Decimal, Decimal, list]:
    """
    Returns (gross_pay, pensionable_pay, earnings_breakdown).
    pensionable_pay follows allowance flags (used by Kenya NSSF tiers).
    """
    factor = decimalize(pro_rata_factor) if pro_rata_factor is not None else Decimal('1')
    pr_days = pro_rata_calendar_days
    denom = Decimal(PRORATA_STANDARD_MONTH_DAYS)

    def prorate_monthly(monthly_val: Decimal) -> Decimal:
        v = decimalize(monthly_val)
        if pr_days is not None:
            return (v / denom) * Decimal(pr_days)
        return v * factor

    other_earn = decimalize(other_earnings)
    basic = prorate_monthly(basic_salary)

    if allowance_breakdown:
        total_allowances = Decimal('0')
        pensionable_allowances = Decimal('0')
        earnings_breakdown = [{'code': 'BASIC', 'name': 'Basic Salary', 'amount': float(basic)}]
        for a in allowance_breakdown:
            should_prorate_line = a.get('prorate', True)
            base_amt = decimalize(a.get('amount', 0))
            amt = prorate_monthly(base_amt) if should_prorate_line else base_amt
            total_allowances += amt
            if a.get('is_pensionable'):
                pensionable_allowances += amt
            earnings_breakdown.append({
                'code': a.get('code', 'ALLOW'),
                'name': a.get('name', 'Allowance'),
                'amount': float(amt),
            })
        other_earn_adj = prorate_monthly(other_earn) if pr_days is not None else other_earn
        earnings_breakdown.append(
            {'code': 'OTHER_EARN', 'name': 'Other Earnings', 'amount': float(other_earn_adj)}
        )
        gross_pay = (basic + total_allowances + other_earn_adj).quantize(Decimal('0.01'))
        pensionable = get_pensionable_pay(basic, pensionable_allowances, Decimal('0'))
    else:
        house = prorate_monthly(decimalize(house_allowance))
        transport = prorate_monthly(decimalize(transport_allowance))
        meal = prorate_monthly(decimalize(meal_allowance))
        other_allow = prorate_monthly(decimalize(other_allowances))
        other_earn_adj = prorate_monthly(other_earn)
        gross_pay = (basic + house + transport + meal + other_allow + other_earn_adj).quantize(
            Decimal('0.01')
        )
        pensionable = get_pensionable_pay(basic, house, Decimal('0'))
        earnings_breakdown = [
            {'code': 'BASIC', 'name': 'Basic Salary', 'amount': float(basic)},
            {'code': 'HOUSE', 'name': 'House Allowance', 'amount': float(house)},
            {'code': 'TRANSPORT', 'name': 'Transport Allowance', 'amount': float(transport)},
            {'code': 'MEAL', 'name': 'Meal Allowance', 'amount': float(meal)},
            {
                'code': 'OTHER_ALLOW',
                'name': 'Other Allowances',
                'amount': float(other_allow + other_earn_adj),
            },
        ]

    ot_days = decimalize(overtime_days) if overtime_days is not None else Decimal('0')
    if ot_days > 0:
        per_day = (gross_pay * Decimal('12')) / Decimal('365')
        ot_amt = (per_day * ot_days).quantize(Decimal('0.01'))
        earnings_breakdown.append(
            {'code': 'OVERTIME', 'name': 'Overtime compensation', 'amount': float(ot_amt)}
        )
        gross_pay = (gross_pay + ot_amt).quantize(Decimal('0.01'))
        pensionable = (pensionable + ot_amt).quantize(Decimal('0.01'))

    return gross_pay, pensionable, earnings_breakdown
