"""Report generation."""
import csv
from datetime import date, datetime
from io import BytesIO, StringIO
from decimal import Decimal
from xml.sax.saxutils import escape as _xml_escape

from flask import Blueprint, abort, current_app, render_template, request, send_file
from flask_login import login_required, current_user
from app.decorators.permissions import permission_required
from app.extensions import db
from sqlalchemy.orm import joinedload

from app.models.payroll import PayrollRun, PayrollStatutoryRemittance
from app.models.employee import Employee
from app.models.department import Department
from app.models.employer import Employer
from app.services.p9_service import MONTH_NAMES, row_for_employee, rows_for_csv
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

reports_bp = Blueprint('reports', __name__)
PDF_MARGIN = 12


@reports_bp.route('/')
@login_required
@permission_required('view_reports')
def index():
    return render_template('reports/index.html')


def _employee_list_query():
    """Build filtered Employee query with department/job_title loaded."""
    q = db.session.query(Employee).options(
        joinedload(Employee.department),
        joinedload(Employee.job_title),
    )
    status = request.args.get('status', '').strip()
    department_id = request.args.get('department_id', type=int)
    search = request.args.get('q', '').strip()
    if status:
        q = q.filter(Employee.status == status)
    if department_id:
        q = q.filter(Employee.department_id == department_id)
    if search:
        like = f'%{search}%'
        q = q.filter(
            db.or_(
                Employee.first_name.ilike(like),
                Employee.last_name.ilike(like),
                Employee.employee_number.ilike(like),
                Employee.email.ilike(like),
            )
        )
    return q.order_by(Employee.employee_number)


def _get_employer_name_pin(default_name='Employer', default_pin='—'):
    """Employer identifiers used in documents; falls back to config for backward compatibility."""
    emp = db.session.query(Employer).order_by(Employer.id.asc()).first()
    config_name = current_app.config.get('EMPLOYER_NAME') or ''
    config_pin = current_app.config.get('EMPLOYER_KRA_PIN') or ''

    name = (emp.name if emp and emp.name else '') or config_name or default_name
    pin = (emp.kra_pin if emp and emp.kra_pin else '') or config_pin or default_pin
    return name, pin


def _p9_access_own_only() -> bool:
    """True when user may only view their own P9 (not full reports permission)."""
    return bool(current_user.is_authenticated and not current_user.has_permission('view_reports'))


def _p9_require_own_employee(employee_id: int) -> None:
    """403 unless HR reports access or viewing own employee record."""
    if current_user.has_permission('view_reports'):
        return
    if not current_user.employee_id or int(current_user.employee_id) != int(employee_id):
        abort(403)


@reports_bp.route('/employee-list')
@login_required
@permission_required('view_reports')
def employee_list():
    employees = _employee_list_query().all()
    departments = db.session.query(Department).order_by(Department.name).all()
    return render_template(
        'reports/employee_list.html',
        employees=employees,
        departments=departments,
    )


@reports_bp.route('/employee-list/csv')
@login_required
@permission_required('view_reports')
def employee_list_csv():
    employees = _employee_list_query().all()
    si = StringIO()
    w = csv.writer(si)
    w.writerow(
        [
            'employee_number',
            'full_name',
            'email',
            'phone',
            'department',
            'job_title',
            'status',
            'hire_date',
            'kra_pin',
            'nssf_number',
            'shif_nhif_number',
        ]
    )
    for e in employees:
        dept = e.department.name if e.department else ''
        jt = e.job_title.name if e.job_title else ''
        w.writerow(
            [
                e.employee_number,
                e.full_name,
                (e.email or '').strip(),
                (e.phone or '').strip(),
                dept,
                jt,
                e.status or '',
                e.hire_date.isoformat() if e.hire_date else '',
                (e.kra_pin or '').strip(),
                (e.nssf_number or '').strip(),
                (e.nhif_number or '').strip(),
            ]
        )
    out = BytesIO()
    out.write(si.getvalue().encode('utf-8-sig'))
    out.seek(0)
    return send_file(
        out,
        as_attachment=True,
        download_name='employee-list.csv',
        mimetype='text/csv; charset=utf-8',
    )


@reports_bp.route('/payroll-summary')
@login_required
@permission_required('view_reports')
def payroll_summary():
    return render_template('reports/payroll_summary.html')


def _build_nssf_rows(run_id: int):
    """Return NSSF per-employee rows and totals for one approved run."""
    rows = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(
            PayrollStatutoryRemittance.payroll_run_id == run_id,
            PayrollStatutoryRemittance.statutory_code.in_(['NSSF_EMPLOYEE', 'NSSF_EMPLOYER']),
        )
        .order_by(PayrollStatutoryRemittance.employee_id, PayrollStatutoryRemittance.statutory_code)
        .all()
    )
    by_employee = {}
    for r in rows:
        key = r.employee_id
        if key not in by_employee:
            by_employee[key] = {
                'employee': r.employee,
                'nssf_number': (r.employee.nssf_number if r.employee else None) or '-',
                'employee_cont': Decimal('0.00'),
                'employer_cont': Decimal('0.00'),
            }
        if r.statutory_code == 'NSSF_EMPLOYEE':
            by_employee[key]['employee_cont'] += Decimal(str(r.amount or 0))
        elif r.statutory_code == 'NSSF_EMPLOYER':
            by_employee[key]['employer_cont'] += Decimal(str(r.amount or 0))

    out = []
    total_employee = Decimal('0.00')
    total_employer = Decimal('0.00')
    for emp_id, entry in by_employee.items():
        employee_name = entry['employee'].full_name if entry['employee'] else f'Employee #{emp_id}'
        total = (entry['employee_cont'] + entry['employer_cont']).quantize(Decimal('0.01'))
        total_employee += entry['employee_cont']
        total_employer += entry['employer_cont']
        out.append(
            {
                'employee_id': emp_id,
                'nssf_number': entry['nssf_number'],
                'employee_name': employee_name,
                'employee_cont': entry['employee_cont'].quantize(Decimal('0.01')),
                'employer_cont': entry['employer_cont'].quantize(Decimal('0.01')),
                'total': total,
            }
        )
    out.sort(key=lambda x: x['employee_name'])
    grand_total = (total_employee + total_employer).quantize(Decimal('0.01'))
    return out, total_employee.quantize(Decimal('0.01')), total_employer.quantize(Decimal('0.01')), grand_total


@reports_bp.route('/nssf')
@login_required
@permission_required('view_reports')
def nssf_report():
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.status == 'approved')
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    selected_run_id = request.args.get('run_id', type=int)
    selected_run = None
    rows = []
    total_employee = Decimal('0.00')
    total_employer = Decimal('0.00')
    grand_total = Decimal('0.00')
    if selected_run_id:
        selected_run = db.session.get(PayrollRun, selected_run_id)
        if selected_run and selected_run.status == 'approved':
            rows, total_employee, total_employer, grand_total = _build_nssf_rows(selected_run_id)
        else:
            selected_run = None
    return render_template(
        'reports/nssf_report.html',
        runs=runs,
        selected_run=selected_run,
        rows=rows,
        total_employee=total_employee,
        total_employer=total_employer,
        grand_total=grand_total,
    )


@reports_bp.route('/nssf/pdf')
@login_required
@permission_required('view_reports')
def nssf_report_pdf():
    run_id = request.args.get('run_id', type=int)
    run_obj = db.session.get(PayrollRun, run_id) if run_id else None
    if not run_obj or run_obj.status != 'approved':
        from flask import abort
        abort(400)

    rows, total_employee, total_employer, grand_total = _build_nssf_rows(run_obj.id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("NSSF Payments Report", styles['Title']),
        Paragraph(f"Payroll Period: {run_obj.pay_month}/{run_obj.pay_year}", styles['Normal']),
        Spacer(1, 12),
    ]
    table_data = [['NSSF No', 'Employee Name', 'Employee Cont', 'Employer Cont', 'Total']]
    for r in rows:
        table_data.append(
            [
                r['nssf_number'],
                r['employee_name'],
                f"{r['employee_cont']:,.2f}",
                f"{r['employer_cont']:,.2f}",
                f"{r['total']:,.2f}",
            ]
        )
    table_data.append(['', 'TOTAL', f"{total_employee:,.2f}", f"{total_employer:,.2f}", f"{grand_total:,.2f}"])
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[doc.width * 0.16, doc.width * 0.34, doc.width * 0.17, doc.width * 0.17, doc.width * 0.16],
        hAlign='LEFT',
    )
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8f9fa')),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    filename = f"nssf-payments-{run_obj.pay_year}-{run_obj.pay_month:02d}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


def _build_paye_rows(run_id: int):
    """Return PAYE rows per employee and total for one approved run."""
    rows = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(
            PayrollStatutoryRemittance.payroll_run_id == run_id,
            PayrollStatutoryRemittance.statutory_code == 'PAYE',
        )
        .order_by(PayrollStatutoryRemittance.employee_id)
        .all()
    )
    out = []
    total = Decimal('0.00')
    for r in rows:
        amount = Decimal(str(r.amount or 0)).quantize(Decimal('0.01'))
        emp_name = r.employee.full_name if r.employee else f'Employee #{r.employee_id}'
        pin = (r.employee.kra_pin if r.employee else None) or '-'
        out.append(
            {
                'employee_id': r.employee_id,
                'pin': pin,
                'employee_name': emp_name,
                'paye_amount': amount,
            }
        )
        total += amount
    out.sort(key=lambda x: x['employee_name'])
    return out, total.quantize(Decimal('0.01'))


@reports_bp.route('/paye')
@login_required
@permission_required('view_reports')
def paye_report():
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.status == 'approved')
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    selected_run_id = request.args.get('run_id', type=int)
    selected_run = None
    rows = []
    total = Decimal('0.00')
    if selected_run_id:
        selected_run = db.session.get(PayrollRun, selected_run_id)
        if selected_run and selected_run.status == 'approved':
            rows, total = _build_paye_rows(selected_run_id)
        else:
            selected_run = None
    return render_template(
        'reports/paye_report.html',
        runs=runs,
        selected_run=selected_run,
        rows=rows,
        total=total,
    )


@reports_bp.route('/paye/pdf')
@login_required
@permission_required('view_reports')
def paye_report_pdf():
    run_id = request.args.get('run_id', type=int)
    run_obj = db.session.get(PayrollRun, run_id) if run_id else None
    if not run_obj or run_obj.status != 'approved':
        from flask import abort
        abort(400)

    rows, total = _build_paye_rows(run_obj.id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("PAYE Report", styles['Title']),
        Paragraph(f"Payroll Period: {run_obj.pay_month}/{run_obj.pay_year}", styles['Normal']),
        Spacer(1, 12),
    ]
    table_data = [['PIN', 'Employee Name', 'PAYE Amount']]
    for r in rows:
        table_data.append([r['pin'], r['employee_name'], f"{r['paye_amount']:,.2f}"])
    table_data.append(['', 'TOTAL', f"{total:,.2f}"])
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[doc.width * 0.28, doc.width * 0.47, doc.width * 0.25],
        hAlign='LEFT',
    )
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8f9fa')),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    filename = f"paye-report-{run_obj.pay_year}-{run_obj.pay_month:02d}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


def _build_sha_rows(run_id: int):
    """Return SHA (SHIF) rows per employee and total for one approved run."""
    rows = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(
            PayrollStatutoryRemittance.payroll_run_id == run_id,
            PayrollStatutoryRemittance.statutory_code == 'SHIF',
        )
        .order_by(PayrollStatutoryRemittance.employee_id)
        .all()
    )
    out = []
    total = Decimal('0.00')
    for r in rows:
        amount = Decimal(str(r.amount or 0)).quantize(Decimal('0.01'))
        emp_name = r.employee.full_name if r.employee else f'Employee #{r.employee_id}'
        sha_no = (r.employee.nhif_number if r.employee else None) or '-'
        out.append(
            {
                'employee_id': r.employee_id,
                'sha_no': sha_no,
                'employee_name': emp_name,
                'sha_amount': amount,
            }
        )
        total += amount
    out.sort(key=lambda x: x['employee_name'])
    return out, total.quantize(Decimal('0.01'))


@reports_bp.route('/sha')
@login_required
@permission_required('view_reports')
def sha_report():
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.status == 'approved')
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    selected_run_id = request.args.get('run_id', type=int)
    selected_run = None
    rows = []
    total = Decimal('0.00')
    if selected_run_id:
        selected_run = db.session.get(PayrollRun, selected_run_id)
        if selected_run and selected_run.status == 'approved':
            rows, total = _build_sha_rows(selected_run_id)
        else:
            selected_run = None
    return render_template(
        'reports/sha_report.html',
        runs=runs,
        selected_run=selected_run,
        rows=rows,
        total=total,
    )


@reports_bp.route('/sha/pdf')
@login_required
@permission_required('view_reports')
def sha_report_pdf():
    run_id = request.args.get('run_id', type=int)
    run_obj = db.session.get(PayrollRun, run_id) if run_id else None
    if not run_obj or run_obj.status != 'approved':
        from flask import abort
        abort(400)

    rows, total = _build_sha_rows(run_obj.id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("SHA (SHIF) Report", styles['Title']),
        Paragraph(f"Payroll Period: {run_obj.pay_month}/{run_obj.pay_year}", styles['Normal']),
        Spacer(1, 12),
    ]
    table_data = [['SHA No', 'Employee Name', 'SHA Amount']]
    for r in rows:
        table_data.append([r['sha_no'], r['employee_name'], f"{r['sha_amount']:,.2f}"])
    table_data.append(['', 'TOTAL', f"{total:,.2f}"])
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[doc.width * 0.28, doc.width * 0.47, doc.width * 0.25],
        hAlign='LEFT',
    )
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8f9fa')),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    filename = f"sha-report-{run_obj.pay_year}-{run_obj.pay_month:02d}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


def _build_housing_levy_rows(run_id: int):
    """
    Return Housing Levy rows per employee and totals for one approved run.
    Employee contribution comes from statutory snapshots (HOUSING_LEVY).
    Employer contribution is mirrored 1:1 for reporting purposes.
    """
    rows = (
        db.session.query(PayrollStatutoryRemittance)
        .filter(
            PayrollStatutoryRemittance.payroll_run_id == run_id,
            PayrollStatutoryRemittance.statutory_code == 'HOUSING_LEVY',
        )
        .order_by(PayrollStatutoryRemittance.employee_id)
        .all()
    )
    out = []
    total_employee = Decimal('0.00')
    total_employer = Decimal('0.00')
    for r in rows:
        employee_cont = Decimal(str(r.amount or 0)).quantize(Decimal('0.01'))
        employer_cont = employee_cont
        emp_name = r.employee.full_name if r.employee else f'Employee #{r.employee_id}'
        pin = (r.employee.kra_pin if r.employee else None) or '-'
        total = (employee_cont + employer_cont).quantize(Decimal('0.01'))
        out.append(
            {
                'employee_id': r.employee_id,
                'pin': pin,
                'employee_name': emp_name,
                'employee_cont': employee_cont,
                'employer_cont': employer_cont,
                'total': total,
            }
        )
        total_employee += employee_cont
        total_employer += employer_cont
    out.sort(key=lambda x: x['employee_name'])
    grand_total = (total_employee + total_employer).quantize(Decimal('0.01'))
    return (
        out,
        total_employee.quantize(Decimal('0.01')),
        total_employer.quantize(Decimal('0.01')),
        grand_total,
    )


@reports_bp.route('/housing-levy')
@login_required
@permission_required('view_reports')
def housing_levy_report():
    runs = (
        db.session.query(PayrollRun)
        .filter(PayrollRun.status == 'approved')
        .order_by(PayrollRun.pay_year.desc(), PayrollRun.pay_month.desc())
        .all()
    )
    selected_run_id = request.args.get('run_id', type=int)
    selected_run = None
    rows = []
    total_employee = Decimal('0.00')
    total_employer = Decimal('0.00')
    grand_total = Decimal('0.00')
    if selected_run_id:
        selected_run = db.session.get(PayrollRun, selected_run_id)
        if selected_run and selected_run.status == 'approved':
            rows, total_employee, total_employer, grand_total = _build_housing_levy_rows(selected_run_id)
        else:
            selected_run = None
    return render_template(
        'reports/housing_levy_report.html',
        runs=runs,
        selected_run=selected_run,
        rows=rows,
        total_employee=total_employee,
        total_employer=total_employer,
        grand_total=grand_total,
    )


@reports_bp.route('/housing-levy/pdf')
@login_required
@permission_required('view_reports')
def housing_levy_report_pdf():
    run_id = request.args.get('run_id', type=int)
    run_obj = db.session.get(PayrollRun, run_id) if run_id else None
    if not run_obj or run_obj.status != 'approved':
        from flask import abort
        abort(400)

    rows, total_employee, total_employer, grand_total = _build_housing_levy_rows(run_obj.id)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=18,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Housing Levy Report", styles['Title']),
        Paragraph(f"Payroll Period: {run_obj.pay_month}/{run_obj.pay_year}", styles['Normal']),
        Spacer(1, 12),
    ]
    table_data = [['PIN', 'Employee Name', 'Employee Cont', 'Employer Cont', 'Total']]
    for r in rows:
        table_data.append(
            [
                r['pin'],
                r['employee_name'],
                f"{r['employee_cont']:,.2f}",
                f"{r['employer_cont']:,.2f}",
                f"{r['total']:,.2f}",
            ]
        )
    table_data.append(['', 'TOTAL', f"{total_employee:,.2f}", f"{total_employer:,.2f}", f"{grand_total:,.2f}"])
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[doc.width * 0.16, doc.width * 0.34, doc.width * 0.17, doc.width * 0.17, doc.width * 0.16],
        hAlign='LEFT',
    )
    table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f8f9fa')),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    filename = f"housing-levy-report-{run_obj.pay_year}-{run_obj.pay_month:02d}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


@reports_bp.route('/p9')
@login_required
def p9_report():
    """P9-style annual PAYE (calendar year) from approved payroll runs."""
    can_view_all = current_user.has_permission('view_reports')
    if _p9_access_own_only() and not current_user.employee_id:
        abort(403)
    year_list = [
        r[0]
        for r in db.session.query(PayrollRun.pay_year)
        .filter(PayrollRun.status == 'approved')
        .distinct()
        .order_by(PayrollRun.pay_year.desc())
        .all()
    ]
    if not year_list:
        year_list = [date.today().year]
    if can_view_all:
        employees = (
            db.session.query(Employee)
            .filter(Employee.status == 'active')
            .order_by(Employee.first_name, Employee.last_name)
            .all()
        )
    else:
        own = db.session.get(Employee, current_user.employee_id)
        employees = [own] if own else []
    selected_year = request.args.get('year', type=int)
    selected_employee_id = request.args.get('employee_id', type=int)
    if not can_view_all:
        selected_employee_id = current_user.employee_id
    preview = None
    if selected_year and selected_employee_id:
        preview = row_for_employee(selected_year, selected_employee_id)
    employer = db.session.query(Employer).order_by(Employer.id.asc()).first()
    employer_display_name, employer_display_pin = _get_employer_name_pin(
        default_name='—',
        default_pin='—',
    )
    return render_template(
        'reports/p9_report.html',
        year_list=year_list,
        employees=employees,
        selected_year=selected_year,
        selected_employee_id=selected_employee_id,
        preview=preview,
        month_names=MONTH_NAMES,
        employer=employer,
        employer_display_name=employer_display_name,
        employer_display_pin=employer_display_pin,
        can_view_all_p9=can_view_all,
    )


@reports_bp.route('/p9/pdf')
@login_required
def p9_pdf():
    year = request.args.get('year', type=int)
    employee_id = request.args.get('employee_id', type=int)
    if not year or not employee_id:
        abort(400)
    _p9_require_own_employee(employee_id)
    data = row_for_employee(year, employee_id)
    if not data:
        abort(404)
    emp = data['employee']
    employer_name, employer_pin = _get_employer_name_pin(default_name='Employer', default_pin='—')

    emp_name = emp.full_name if emp else f'Employee #{employee_id}'
    emp_pin = (emp.kra_pin or '—').strip() if emp else '—'
    emp_no = emp.employee_number if emp else '—'
    id_no = (emp.national_id or '—').strip() if emp else '—'

    monthly_rows = data['monthly_rows']
    monthly_totals = data['monthly_totals']

    def _kes(v) -> str:
        try:
            return f"{float(v):,.2f}"
        except (TypeError, ValueError):
            return '0.00'

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=PDF_MARGIN,
        rightMargin=PDF_MARGIN,
        topMargin=14,
        bottomMargin=18,
    )
    styles = getSampleStyleSheet()
    header_data = [
        ['Employer', _xml_escape(employer_name), 'Tax year', _xml_escape(str(year))],
        ['Employer Tax-PIN', _xml_escape(employer_pin), "Tax payer's name", _xml_escape(emp_name)],
        ['Employee no.', _xml_escape(str(emp_no)), 'ID no.', _xml_escape(str(id_no))],
        ['PIN', _xml_escape(emp_pin), '', ''],
    ]
    hw = doc.width
    header_tbl = Table(
        header_data,
        colWidths=[hw * 0.16, hw * 0.34, hw * 0.16, hw * 0.34],
        hAlign='LEFT',
    )
    header_tbl.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f1f5f9')),
                ('BACKGROUND', (2, 0), (2, 2), colors.HexColor('#f1f5f9')),
                ('BACKGROUND', (0, 3), (0, 3), colors.HexColor('#f1f5f9')),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (2, 0), (2, 2), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('SPAN', (1, 3), (3, 3)),
            ]
        )
    )
    story = [
        Paragraph(
            '<b>P9 — End of Year Tax Returns</b>',
            styles['Title'],
        ),
        Spacer(1, 6),
        header_tbl,
        Spacer(1, 10),
    ]

    hdr = [
        'Pay date',
        'Taxable pay (KES)',
        'Pension (KES)',
        'PAYE auto (KES)',
        'Unused MPR (KES)',
        'MPR value (KES)',
        'Arrears (KES)',
        'PAYE manual (KES)',
    ]
    table_data = [hdr]
    for r in monthly_rows:
        table_data.append(
            [
                r['pay_date'],
                _kes(r['taxable_pay']),
                _kes(r['pension']),
                _kes(r['paye_auto']),
                _kes(r['unused_mpr']),
                _kes(r['mpr_value']),
                _kes(r['arrears']),
                _kes(r['paye_manual']),
            ]
        )
    table_data.append(
        [
            'Totals',
            _kes(monthly_totals['taxable_pay']),
            _kes(monthly_totals['pension']),
            _kes(monthly_totals['paye_auto']),
            _kes(monthly_totals['unused_mpr']),
            _kes(monthly_totals['mpr_value']),
            _kes(monthly_totals['arrears']),
            _kes(monthly_totals['paye_manual']),
        ]
    )

    col_fracs = [0.11, 0.13, 0.11, 0.13, 0.13, 0.13, 0.13, 0.13]
    col_widths = [doc.width * f for f in col_fracs]
    p9_table = Table(table_data, repeatRows=1, colWidths=col_widths, hAlign='LEFT')
    p9_table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#cfe2ff')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e9ecef')),
            ]
        )
    )
    story.append(p9_table)
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            f'<i>Printed at {_xml_escape(datetime.now().strftime("%d/%m/%Y, %H:%M:%S"))}</i>',
            styles['Normal'],
        )
    )
    doc.build(story)
    buffer.seek(0)
    filename = f"p9-paye-{year}-emp-{employee_id}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


@reports_bp.route('/p9/csv')
@login_required
def p9_csv():
    """iTax-oriented CSV: one row per employee, monthly PAYE + yearly P9 totals."""
    year = request.args.get('year', type=int)
    employee_id = request.args.get('employee_id', type=int)
    if not year:
        abort(400)
    if _p9_access_own_only():
        if not current_user.employee_id:
            abort(403)
        employee_id = current_user.employee_id
    rows = rows_for_csv(year)
    if employee_id:
        rows = [r for r in rows if r['employee_id'] == employee_id]
    employer_name, employer_pin = _get_employer_name_pin(default_name='', default_pin='')
    si = StringIO()
    w = csv.writer(si)
    header = [
        'employer_kra_pin',
        'employer_name',
        'employee_number',
        'employee_kra_pin',
        'employee_name',
        'gross_pay_yearly',
        'benefits_other_cash_yearly',
        'chargeable_income_paye_basis_yearly',
        'tax_before_personal_relief_yearly',
        'personal_relief_applied_yearly',
        'paye_deducted_yearly',
        'nssf_employee_yearly',
        'nssf_employer_yearly',
        'shif_yearly',
        'housing_levy_employee_yearly',
    ] + [f'paye_{m:02d}_{MONTH_NAMES[m - 1].lower()}' for m in range(1, 13)]
    w.writerow(header)
    for r in rows:
        w.writerow(
            [
                employer_pin,
                employer_name,
                r['employee_number'],
                r['pin'],
                r['name'],
                str(r['gross_pay_yearly']),
                str(r['benefits_yearly']),
                str(r['chargeable_income_yearly']),
                str(r['tax_before_relief_yearly']),
                str(r['personal_relief_yearly']),
                str(r['total_paye']),
                str(r['nssf_employee_yearly']),
                str(r['nssf_employer_yearly']),
                str(r['shif_yearly']),
                str(r['housing_levy_yearly']),
            ]
            + [str(r[f'm{m}']) for m in range(1, 13)]
        )
    out = BytesIO()
    out.write(si.getvalue().encode('utf-8-sig'))
    out.seek(0)
    suffix = f'-emp-{employee_id}' if employee_id else '-all'
    filename = f"p9-itax-{year}{suffix}.csv"
    return send_file(
        out,
        as_attachment=True,
        download_name=filename,
        mimetype='text/csv; charset=utf-8',
    )
