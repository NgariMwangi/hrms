"""
Core payroll calculation engine for Kenya.
Uses statutory_service for PAYE, NSSF, SHIF, Housing Levy.
Produces gross, taxable pay, deductions, net. Optionally pro-rata for mid-month join/exit.
Pension % on salary is stored for reference; it does not reduce PAYE taxable pay or net pay here.
Net pay matches statutory deductions: PAYE, NSSF, SHIF, Housing levy, and other deductions (same as payslip total).
"""
from datetime import date, timedelta
from decimal import Decimal
from app.services.statutory_service import (
    get_pensionable_pay,
    calculate_nssf,
    calculate_nssf_with_breakdown,
    calculate_paye,
    calculate_shif,
    calculate_housing_levy,
)
from app.services.deduction_service import get_recurring_deduction_line_items

def decimalize(value) -> Decimal:
    """Ensure value is Decimal."""
    if value is None:
        return Decimal('0')
    return Decimal(str(value))


def get_working_days_in_month(year: int, month: int) -> int:
    """Working days in month (simplified: exclude weekends only)."""
    from calendar import monthrange
    wd = 0
    _, last = monthrange(year, month)
    for d in range(1, last + 1):
        dte = date(year, month, d)
        if dte.weekday() < 5:  # Mon=0 .. Fri=4
            wd += 1
    return wd


def pro_rata_factor(hire_date: date, termination_date: date, pay_month: int, pay_year: int) -> Decimal:
    """
    Factor for pro-rating (0-1) for partial month.
    hire_date/termination_date can be None for full month.
    """
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
        return Decimal('0')
    working_days = get_working_days_in_month(pay_year, pay_month)
    days_worked = sum(1 for d in range((work_end - work_start).days + 1)
                      if (work_start + timedelta(days=d)).weekday() < 5)
    if working_days <= 0:
        return Decimal('0')
    return (Decimal(days_worked) / Decimal(working_days)).quantize(Decimal('0.0001'))


def calculate_employee_payroll(
    basic_salary: Decimal,
    house_allowance: Decimal = None,
    transport_allowance: Decimal = None,
    meal_allowance: Decimal = None,
    other_allowances: Decimal = None,
    pension_employee_percent: Decimal = None,
    pay_date: date = None,
    pro_rata_factor: Decimal = None,
    other_earnings: Decimal = None,
    other_deductions: Decimal = None,
    allowance_breakdown: list = None,
    employee_id: int = None,
    manual_deduction_lines: list = None,
) -> dict:
    """
    Calculate single employee's pay for the month.
    If allowance_breakdown is provided (list of dicts with amount, is_taxable, is_pensionable, code, name),
    it is used instead of house/transport/meal/other. Otherwise legacy columns are used.
    Returns dict: gross_pay, pensionable_pay, ..., earnings_breakdown, deductions_breakdown.

    employee_id: if set, active recurring EmployeeDeduction rows are applied (see deduction_service).
    manual_deduction_lines: optional list of dicts {code, name, amount (Decimal)} from draft payroll run overrides.
    other_deductions: legacy fixed amount added to the same bucket (rarely used).
    """
    pay_date = pay_date or date.today()
    factor = decimalize(pro_rata_factor) if pro_rata_factor is not None else Decimal('1')
    other_earn = decimalize(other_earnings)
    legacy_other = decimalize(other_deductions)
    pension_pct = decimalize(pension_employee_percent)
    basic = decimalize(basic_salary) * factor

    if allowance_breakdown:
        total_allowances = Decimal('0')
        pensionable_allowances = Decimal('0')
        earnings_breakdown = [{'code': 'BASIC', 'name': 'Basic Salary', 'amount': float(basic)}]
        for a in allowance_breakdown:
            amt = decimalize(a.get('amount', 0)) * factor
            total_allowances += amt
            if a.get('is_pensionable'):
                pensionable_allowances += amt
            earnings_breakdown.append({
                'code': a.get('code', 'ALLOW'),
                'name': a.get('name', 'Allowance'),
                'amount': float(amt),
            })
        earnings_breakdown.append({'code': 'OTHER_EARN', 'name': 'Other Earnings', 'amount': float(other_earn)})
        gross_pay = (basic + total_allowances + other_earn).quantize(Decimal('0.01'))
        pensionable = get_pensionable_pay(basic, pensionable_allowances, Decimal('0'))
    else:
        transport = decimalize(transport_allowance)
        meal = decimalize(meal_allowance)
        other_allow = decimalize(other_allowances)
        house = decimalize(house_allowance)
        house = house * factor
        transport = transport * factor
        meal = meal * factor
        other_allow = other_allow * factor
        other_earn = other_earn * factor
        gross_pay = (basic + house + transport + meal + other_allow + other_earn).quantize(Decimal('0.01'))
        pensionable = get_pensionable_pay(basic, house, Decimal('0'))
        earnings_breakdown = [
            {'code': 'BASIC', 'name': 'Basic Salary', 'amount': float(basic)},
            {'code': 'HOUSE', 'name': 'House Allowance', 'amount': float(house)},
            {'code': 'TRANSPORT', 'name': 'Transport Allowance', 'amount': float(transport)},
            {'code': 'MEAL', 'name': 'Meal Allowance', 'amount': float(meal)},
            {'code': 'OTHER_ALLOW', 'name': 'Other Allowances', 'amount': float(other_allow + other_earn)},
        ]

    nssf_emp, nssf_empr, nssf_breakdown = calculate_nssf_with_breakdown(pensionable, pay_date)
    nssf_emp = nssf_emp.quantize(Decimal('0.01'))
    nssf_empr = nssf_empr.quantize(Decimal('0.01'))

    shif = calculate_shif(gross_pay, pay_date)
    housing_levy = calculate_housing_levy(gross_pay, pay_date)
    pension_deduction = (gross_pay * pension_pct / 100).quantize(Decimal('0.01')) if pension_pct else Decimal('0')
    # PAYE taxable pay: gross less NSSF (employee), SHIF, and Housing Levy only (not pension).
    taxable_pay = (gross_pay - nssf_emp - shif - housing_levy).quantize(Decimal('0.01'))
    if taxable_pay < 0:
        taxable_pay = Decimal('0')
    paye = calculate_paye(taxable_pay, pay_date)
    recurring_lines = (
        get_recurring_deduction_line_items(employee_id, pay_date, gross_pay, basic)
        if employee_id
        else []
    )
    manual_lines = list(manual_deduction_lines or [])
    extra_lines = recurring_lines + manual_lines
    other_ded = legacy_other + sum((x['amount'] for x in extra_lines), start=Decimal('0'))
    other_ded = other_ded.quantize(Decimal('0.01'))
    # Net pay = statutory deductions + other/recurring/manual deductions; pension is not subtracted here.
    total_deductions = nssf_emp + shif + housing_levy + paye + other_ded
    net_pay = (gross_pay - total_deductions).quantize(Decimal('0.01'))
    deductions_breakdown = []
    for row in nssf_breakdown:
        deductions_breakdown.append(
            {
                'code': f"NSSF_TIER{row['tier_number']}",
                'name': f"NSSF (Tier {row['tier_number']})",
                'amount': float(row['employee']),
            }
        )
    if not nssf_breakdown:
        deductions_breakdown.append({'code': 'NSSF', 'name': 'NSSF', 'amount': float(nssf_emp)})
    ext = [
        {'code': 'SHIF', 'name': 'SHIF', 'amount': float(shif)},
        {'code': 'HOUSING_LEVY', 'name': 'Housing Levy', 'amount': float(housing_levy)},
        {'code': 'PAYE', 'name': 'PAYE', 'amount': float(paye)},
    ]
    for x in extra_lines:
        ext.append({'code': x['code'], 'name': x['name'], 'amount': float(x['amount'])})
    if legacy_other and legacy_other > 0:
        ext.append({'code': 'OTHER', 'name': 'Other Deductions (legacy)', 'amount': float(legacy_other)})
    if pension_deduction and pension_deduction > 0:
        ext.insert(
            -1,
            {
                'code': 'PENSION',
                'name': 'Pension (reference — not deducted from net pay)',
                'amount': float(pension_deduction),
            },
        )
    deductions_breakdown.extend(ext)

    return {
        'gross_pay': gross_pay,
        'pensionable_pay': pensionable,
        'nssf_employee': nssf_emp,
        'nssf_employer': nssf_empr,
        'shif': shif,
        'housing_levy': housing_levy,
        'pension_deduction': pension_deduction,
        'taxable_pay': taxable_pay,
        'paye': paye,
        'other_deductions': other_ded,
        'total_deductions': total_deductions,
        'net_pay': net_pay,
        'earnings_breakdown': earnings_breakdown,
        'deductions_breakdown': deductions_breakdown,
    }
