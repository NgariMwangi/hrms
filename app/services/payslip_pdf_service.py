"""Generate compact employee payslip PDF (ReportLab)."""
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.utils.formatters import format_currency

PDF_MARGIN = 48
FONT = 9
FONT_SM = 8
FONT_LG = 11


def _money(amount, currency: str) -> str:
    return format_currency(amount, currency)


def _employee_details_table(emp, width: float) -> Table:
    """Four fields in two columns: name/number | job title/KRA PIN."""
    name = emp.full_name if emp else '—'
    number = (emp.employee_number if emp else None) or '—'
    title = (emp.job_title.name if emp and emp.job_title else None) or '—'
    pin = (emp.kra_pin if emp else None) or '—'
    label_w = width * 0.19
    value_w = width * 0.31
    data = [
        ['Employee name', name, 'Job title', title],
        ['Employee number', number, 'KRA PIN', pin],
    ]
    table = Table(
        data,
        colWidths=[label_w, value_w, label_w, value_w],
        hAlign='LEFT',
    )
    table.setStyle(
        TableStyle(
            [
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), FONT),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#475569')),
                ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#475569')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ]
        )
    )
    return table


def _payslip_lines_table(
    rows: list[tuple[str, str, bool]],
    width: float,
    currency: str,
) -> Table:
    """
    rows: (label, formatted_amount, is_bold)
    Section headers use label only with empty amount and is_bold True.
    """
    data = [['', f'Amount ({currency})']]
    bold_rows: set[int] = set()
    highlight_rows: set[int] = set()
    section_rows: set[int] = set()
    for i, (label, amount, is_bold) in enumerate(rows, start=1):
        data.append([label, amount])
        if is_bold and not amount:
            section_rows.add(i)
            bold_rows.add(i)
        elif is_bold:
            bold_rows.add(i)
        if label == 'Net pay':
            highlight_rows.add(i)
    col_w = width * 0.68, width * 0.32
    table = Table(data, colWidths=list(col_w), hAlign='LEFT')
    style_commands = [
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), FONT),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, 0), (-1, 0), 0.75, colors.HexColor('#334155')),
    ]
    for idx in section_rows:
        style_commands.append(('SPAN', (0, idx), (1, idx)))
        style_commands.append(('BACKGROUND', (0, idx), (-1, idx), colors.HexColor('#f1f5f9')))
    for idx in bold_rows:
        style_commands.append(('FONTNAME', (0, idx), (-1, idx), 'Helvetica-Bold'))
    for idx in highlight_rows:
        style_commands.append(('BACKGROUND', (0, idx), (-1, idx), colors.HexColor('#ecfdf5')))
    table.setStyle(TableStyle(style_commands))
    return table


def build_payslip_pdf(ctx: dict) -> bytes:
    """Build compact payslip PDF from payroll._build_payslip_context."""
    item = ctx['item']
    emp = item.employee
    currency = ctx['payslip_currency']
    period_date = ctx['period_date']
    earnings_lines = ctx['earnings_lines']
    other_deduction_lines = ctx['other_deduction_lines']

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=PDF_MARGIN,
        bottomMargin=PDF_MARGIN,
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name='PayslipCompany',
            parent=styles['Normal'],
            fontSize=FONT_LG,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#0f172a'),
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name='PayslipMeta',
            parent=styles['Normal'],
            fontSize=FONT_SM,
            textColor=colors.HexColor('#64748b'),
        )
    )
    styles.add(
        ParagraphStyle(
            name='PayslipSection',
            parent=styles['Normal'],
            fontSize=FONT,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#334155'),
            spaceBefore=6,
            spaceAfter=4,
        )
    )

    company_name = ctx.get('company_name') or 'Organization'
    period_label = period_date.strftime('%B %Y')
    emp_name = emp.full_name if emp else 'Employee'

    story = [
        Paragraph(company_name, styles['PayslipCompany']),
        Paragraph(
            f'<b>PAYSLIP</b> &nbsp;·&nbsp; {period_label} &nbsp;·&nbsp; {emp_name}',
            styles['PayslipMeta'],
        ),
        Spacer(1, 10),
        Paragraph('Employee details', styles['PayslipSection']),
        _employee_details_table(emp, doc.width),
        Spacer(1, 10),
    ]

    pay_rows: list[tuple[str, str, bool]] = []

    if earnings_lines:
        pay_rows.append(('Earnings', '', True))
        for line in earnings_lines:
            pay_rows.append((line['name'], _money(line['amount'], currency), False))
    pay_rows.append(('Gross pay', _money(item.gross_pay, currency), True))

    pay_rows.append(('Deductions', '', True))
    pay_rows.append(('PAYE', _money(item.paye, currency), False))
    if ctx['show_nssf_tiers']:
        pay_rows.append(('NSSF (Tier I)', _money(ctx['nssf_tier_1'], currency), False))
        pay_rows.append(('NSSF (Tier II)', _money(ctx['nssf_tier_2'], currency), False))
    else:
        pay_rows.append(('NSSF', _money(item.nssf_employee, currency), False))
    if ctx['show_shif']:
        pay_rows.append(('SHIF', _money(item.shif, currency), False))
    if ctx['show_housing_levy']:
        pay_rows.append(('Housing levy', _money(item.housing_levy, currency), False))
    if ctx['pension_percent_amount'] > 0:
        pay_rows.append(('Pension (%)', _money(ctx['pension_percent_amount'], currency), False))
    if ctx['pension_fixed_amount'] > 0:
        pay_rows.append(('Pension (fixed)', _money(ctx['pension_fixed_amount'], currency), False))
    for od in other_deduction_lines:
        try:
            amt = Decimal(str(od.get('amount') or 0))
        except (TypeError, ValueError):
            continue
        if amt == 0:
            continue
        pay_rows.append((od.get('name') or 'Deduction', _money(amt, currency), False))

    pay_rows.append(('Net pay', _money(item.net_pay, currency), True))
    story.append(_payslip_lines_table(pay_rows, doc.width, currency))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
