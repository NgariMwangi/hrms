"""Allowances: full month amount, not prorated; mid-month effective dates included."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.payroll_common import build_allowance_breakdown, build_gross_earnings, pro_rata_factor


def test_allowances_not_prorated_on_partial_month():
    factor = pro_rata_factor(
        hire_date=date(2026, 6, 15),
        termination_date=None,
        pay_month=6,
        pay_year=2026,
    )
    assert factor < Decimal('1')

    result = build_gross_earnings(
        basic_salary=Decimal('30000'),
        house_allowance=Decimal('10000'),
        transport_allowance=Decimal('5000'),
        pro_rata_factor=factor,
        pro_rata_calendar_days=16,
    )
    codes = {line['code']: line['amount'] for line in result.earnings_breakdown}
    assert codes['BASIC'] < 30000.0
    assert codes['HOUSE'] == 10000.0
    assert codes['TRANSPORT'] == 5000.0


def test_allowance_breakdown_not_prorated():
    result = build_gross_earnings(
        basic_salary=Decimal('30000'),
        pro_rata_factor=Decimal('0.5'),
        pro_rata_calendar_days=15,
        allowance_breakdown=[
            {
                'amount': Decimal('8000'),
                'is_taxable': True,
                'is_pensionable': False,
                'prorate': False,
                'code': 'TRANSPORT',
                'name': 'Transport',
            },
        ],
    )
    codes = {line['code']: line['amount'] for line in result.earnings_breakdown}
    assert codes['BASIC'] == 15000.0
    assert codes['TRANSPORT'] == 8000.0


def test_build_allowance_breakdown_merges_catalog_and_salary_fields():
    salary = SimpleNamespace(
        house_allowance=Decimal('5000'),
        transport_allowance=Decimal('3000'),
        meal_allowance=0,
        other_allowances=0,
    )
    catalog_allowance = SimpleNamespace(code='MEAL', name='Meal', is_taxable=True, is_pensionable=False)
    emp_allowance = SimpleNamespace(
        id=1,
        amount=Decimal('2000'),
        allowance=catalog_allowance,
    )
    breakdown = build_allowance_breakdown(salary, [emp_allowance], [])
    codes = {line['code']: line['amount'] for line in breakdown}
    assert codes['MEAL'] == Decimal('2000')
    assert codes['HOUSE'] == Decimal('5000')
    assert codes['TRANSPORT'] == Decimal('3000')
    assert all(line['prorate'] is False for line in breakdown)
