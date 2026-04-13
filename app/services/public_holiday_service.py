"""Public holidays: excluded from working-day leave counts."""
from __future__ import annotations

import calendar
from datetime import date

from app.extensions import db
from app.models.leave import PublicHoliday


def recurring_holiday_date_in_year(year: int, month: int, day: int) -> date:
    """
    Calendar date for a recurring holiday in `year`.
    Feb 29 in a non-leap year becomes Feb 28 (observed).
    """
    last = calendar.monthrange(year, month)[1]
    d = min(day, last)
    return date(year, month, d)


def public_holiday_dates_in_range(start: date, end: date) -> set[date]:
    """All public holiday dates in [start, end] (recurring expanded per year + one-offs)."""
    if start > end:
        return set()
    out: set[date] = set()
    y0, y1 = start.year, end.year

    one_offs = (
        db.session.query(PublicHoliday)
        .filter(
            PublicHoliday.kind == 'one_off',
            PublicHoliday.date.isnot(None),
            PublicHoliday.date >= start,
            PublicHoliday.date <= end,
        )
        .all()
    )
    for h in one_offs:
        out.add(h.date)

    recurring = (
        db.session.query(PublicHoliday)
        .filter(
            PublicHoliday.kind == 'recurring',
            PublicHoliday.recurring_month.isnot(None),
            PublicHoliday.recurring_day.isnot(None),
        )
        .all()
    )
    for h in recurring:
        m, d = h.recurring_month, h.recurring_day
        for y in range(y0, y1 + 1):
            try:
                occ = recurring_holiday_date_in_year(y, m, d)
            except ValueError:
                continue
            if start <= occ <= end:
                out.add(occ)

    return out
