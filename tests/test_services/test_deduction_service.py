"""Deduction effective-date overlap with payroll month."""
from datetime import date

from app.services.deduction_service import deduction_overlaps_pay_period, pay_period_bounds


def test_pay_period_bounds_from_first_of_month():
    start, end = pay_period_bounds(date(2026, 6, 1))
    assert start == date(2026, 6, 1)
    assert end == date(2026, 6, 30)


def test_mid_month_deduction_included_in_same_month():
    period_start, period_end = pay_period_bounds(date(2026, 6, 1))
    assert deduction_overlaps_pay_period(
        effective_from=date(2026, 6, 15),
        effective_to=None,
        period_start=period_start,
        period_end=period_end,
    )


def test_deduction_starting_next_month_excluded():
    period_start, period_end = pay_period_bounds(date(2026, 6, 1))
    assert not deduction_overlaps_pay_period(
        effective_from=date(2026, 7, 1),
        effective_to=None,
        period_start=period_start,
        period_end=period_end,
    )


def test_deduction_ended_before_month_excluded():
    period_start, period_end = pay_period_bounds(date(2026, 6, 1))
    assert not deduction_overlaps_pay_period(
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 5, 31),
        period_start=period_start,
        period_end=period_end,
    )
