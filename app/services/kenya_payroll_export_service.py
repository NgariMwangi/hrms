"""
Kenya payroll run export to Excel (staff payroll items).
"""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from app.extensions import db
from app.models.payroll import PayrollItem, PayrollRun
from sqlalchemy.orm import joinedload

TWO_DP = Decimal('0.01')

KENYA_EXPORT_HEADERS = [
    'Employee Name',
    'Benefits',
    'Gross Pay',
    'Taxable Pay',
    'SHIF',
    'Total NSSF',
    'Welfare Kit',
    'SHELLOYEES SACCO',
    'MAISHA BORA SACCO',
    'Voluntary Pension',
    'PAYE',
    'total_deductions',
    'NET PAY',
]

# Deduction line codes excluded when matching recurring/other columns by name.
_STATUTORY_CODES = frozenset({
    'NSSF', 'SHIF', 'HOUSING_LEVY', 'PAYE',
    'PENSION_PERCENT', 'PENSION_FIXED',
})


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(TWO_DP)
    except Exception:
        return Decimal('0')


def _normalize_name(name: str) -> str:
    return ' '.join((name or '').upper().split())


def _name_matches(name: str, *required_parts: str) -> bool:
    n = _normalize_name(name)
    return all(part.upper() in n for part in required_parts)


def benefits_total(item: PayrollItem) -> Decimal:
    """Sum employee benefit earnings (BEN-* lines) for the period."""
    total = Decimal('0')
    for row in item.earnings_breakdown or []:
        code = str(row.get('code') or '').upper()
        if not code.startswith('BEN-'):
            continue
        total += _decimal(row.get('amount'))
    return total.quantize(TWO_DP)


def _deduction_lines(item: PayrollItem) -> list[dict]:
    return list(item.deductions_breakdown or [])


def _is_statutory_code(code: str) -> bool:
    c = (code or '').upper()
    if c in _STATUTORY_CODES:
        return True
    return c.startswith('NSSF')


def voluntary_pension_total(item: PayrollItem) -> Decimal:
    total = Decimal('0')
    for row in _deduction_lines(item):
        code = (row.get('code') or '').upper()
        if code in ('PENSION_PERCENT', 'PENSION_FIXED'):
            total += _decimal(row.get('amount'))
            continue
        name = row.get('name') or ''
        if _name_matches(name, 'VOLUNTARY', 'PENSION') or _normalize_name(name) == 'VOLUNTARY PENSION':
            total += _decimal(row.get('amount'))
    return total.quantize(TWO_DP)


def _named_deduction_total(item: PayrollItem, *name_parts: str) -> Decimal:
    total = Decimal('0')
    for row in _deduction_lines(item):
        code = (row.get('code') or '').upper()
        if _is_statutory_code(code):
            continue
        if code in ('PENSION_PERCENT', 'PENSION_FIXED'):
            continue
        name = row.get('name') or ''
        if _name_matches(name, *name_parts):
            total += _decimal(row.get('amount'))
    return total.quantize(TWO_DP)


def total_deductions(item: PayrollItem) -> Decimal:
    gross = _decimal(item.gross_pay)
    net = _decimal(item.net_pay)
    return (gross - net).quantize(TWO_DP)


def kenya_export_row(item: PayrollItem) -> dict:
    emp = item.employee
    return {
        'employee_name': emp.full_name if emp else f'Employee #{item.employee_id}',
        'benefits': benefits_total(item),
        'gross_pay': _decimal(item.gross_pay),
        'taxable_pay': _decimal(item.taxable_pay),
        'shif': _decimal(item.shif),
        'total_nssf': _decimal(item.nssf_employee),
        'welfare_kit': _named_deduction_total(item, 'WELFARE', 'KIT'),
        'shelloyees_sacco': _named_deduction_total(item, 'SHELLOYEES', 'SACCO'),
        'maisha_bora_sacco': _named_deduction_total(item, 'MAISHA', 'BORA'),
        'voluntary_pension': voluntary_pension_total(item),
        'paye': _decimal(item.paye),
        'total_deductions': total_deductions(item),
        'net_pay': _decimal(item.net_pay),
    }


def fetch_kenya_payroll_items(run_id: int, company_id: int) -> list[PayrollItem]:
    return (
        db.session.query(PayrollItem)
        .join(PayrollRun, PayrollRun.id == PayrollItem.payroll_run_id)
        .options(joinedload(PayrollItem.employee))
        .filter(
            PayrollItem.payroll_run_id == run_id,
            PayrollRun.company_id == company_id,
        )
        .order_by(PayrollItem.employee_id)
        .all()
    )


def build_kenya_payroll_workbook(run: PayrollRun, items: list[PayrollItem]) -> BytesIO:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment

    wb = Workbook()
    ws = wb.active
    ws.title = f"Payroll {run.pay_year}-{run.pay_month:02d}"

    ws.append(KENYA_EXPORT_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')

    numeric_keys = (
        'benefits', 'gross_pay', 'taxable_pay', 'shif', 'total_nssf',
        'welfare_kit', 'shelloyees_sacco', 'maisha_bora_sacco',
        'voluntary_pension', 'paye', 'total_deductions', 'net_pay',
    )
    totals = {k: Decimal('0') for k in numeric_keys}

    for item in items:
        row = kenya_export_row(item)
        ws.append([
            row['employee_name'],
            float(row['benefits']),
            float(row['gross_pay']),
            float(row['taxable_pay']),
            float(row['shif']),
            float(row['total_nssf']),
            float(row['welfare_kit']),
            float(row['shelloyees_sacco']),
            float(row['maisha_bora_sacco']),
            float(row['voluntary_pension']),
            float(row['paye']),
            float(row['total_deductions']),
            float(row['net_pay']),
        ])
        for k in numeric_keys:
            totals[k] += row[k]

    ws.append([
        'TOTAL',
        float(totals['benefits']),
        float(totals['gross_pay']),
        float(totals['taxable_pay']),
        float(totals['shif']),
        float(totals['total_nssf']),
        float(totals['welfare_kit']),
        float(totals['shelloyees_sacco']),
        float(totals['maisha_bora_sacco']),
        float(totals['voluntary_pension']),
        float(totals['paye']),
        float(totals['total_deductions']),
        float(totals['net_pay']),
    ])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    ws.freeze_panes = 'A2'
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            if cell.value is not None:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_len + 2, 36)

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out
