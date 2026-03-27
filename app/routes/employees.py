"""Employee CRUD and management."""
import os
import mimetypes
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db
from app.models.employee import Employee
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.payroll import EmployeeSalary, EmployeeAllowance, Allowance, EmployeeDeduction
from app.models.user import User, Role, UserRole
from app.models.document import EmployeeDocument, DocumentCategory
from app.forms.employee_forms import EmployeeForm, EmployeeSalaryForm
from app.decorators.permissions import permission_required
from app.services.audit_service import log_create, log_update, model_to_audit_dict
from app.utils.validators import normalize_phone_ke

try:
    import cloudinary
    import cloudinary.uploader
    from cloudinary.utils import cloudinary_url
except Exception:  # pragma: no cover
    cloudinary = None
    cloudinary_url = None

employees_bp = Blueprint('employees', __name__)


def _next_employee_number():
    """Generate EMP-YYYY-####."""
    from datetime import date
    year = date.today().year
    prefix = f"{current_app.config.get('EMPLOYEE_NUMBER_PREFIX', 'EMP')}-{year}-"
    last = db.session.query(Employee).filter(Employee.employee_number.startswith(prefix)).order_by(
        Employee.id.desc()).first()
    num = 1
    if last:
        try:
            num = int(last.employee_number.split('-')[-1]) + 1
        except (IndexError, ValueError):
            pass
    return f"{prefix}{num:04d}"


@employees_bp.route('/')
@login_required
@permission_required('view_employees')
def list():
    q = db.session.query(Employee)
    department_id = request.args.get('department_id', type=int)
    job_title_id = request.args.get('job_title_id', type=int)
    status = request.args.get('status')
    search = request.args.get('q', '').strip()
    if department_id:
        q = q.filter(Employee.department_id == department_id)
    if job_title_id:
        q = q.filter(Employee.job_title_id == job_title_id)
    if status:
        q = q.filter(Employee.status == status)
    if search:
        q = q.filter(
            db.or_(
                Employee.first_name.ilike(f'%{search}%'),
                Employee.last_name.ilike(f'%{search}%'),
                Employee.employee_number.ilike(f'%{search}%'),
                Employee.email.ilike(f'%{search}%'),
            )
        )
    employees = q.order_by(Employee.employee_number).all()
    departments = db.session.query(Department).order_by(Department.name).all()
    return render_template('employees/list.html', employees=employees, departments=departments)


@employees_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('create_employees')
def create():
    form = EmployeeForm()
    form.department_id.choices = [('', '--')] + [(d.id, d.name) for d in db.session.query(Department).order_by(Department.name).all()]
    form.job_title_id.choices = [('', '--')] + [(j.id, j.name) for j in db.session.query(JobTitle).order_by(JobTitle.name).all()]
    form.manager_id.choices = [('', '--')] + [(e.id, e.full_name) for e in db.session.query(Employee).filter(Employee.status == 'active').order_by(Employee.first_name).all()]
    if form.validate_on_submit():
        try:
            emp = Employee(
                employee_number=_next_employee_number(),
                first_name=form.first_name.data,
                last_name=form.last_name.data,
                middle_name=form.middle_name.data or None,
                date_of_birth=form.date_of_birth.data,
                gender=form.gender.data or None,
                marital_status=form.marital_status.data or None,
                nationality=form.nationality.data or None,
                national_id=form.national_id.data or None,
                passport_number=form.passport_number.data or None,
                kra_pin=form.kra_pin.data or None,
                nssf_number=form.nssf_number.data or None,
                nhif_number=form.nhif_number.data or None,
                email=form.email.data or None,
                phone=normalize_phone_ke(form.phone.data) if form.phone.data else None,
                phone_alt=normalize_phone_ke(form.phone_alt.data) if form.phone_alt.data else None,
                address=form.address.data or None,
                postal_address=form.postal_address.data or None,
                emergency_contact_name=form.emergency_contact_name.data or None,
                emergency_contact_phone=form.emergency_contact_phone.data or None,
                department_id=form.department_id.data or None,
                job_title_id=form.job_title_id.data or None,
                manager_id=form.manager_id.data or None,
                status=form.status.data,
                employment_type=form.employment_type.data or None,
                hire_date=form.hire_date.data,
                probation_end_date=form.probation_end_date.data,
                confirmation_date=form.confirmation_date.data,
                contract_end_date=form.contract_end_date.data,
                bank_name=form.bank_name.data or None,
                bank_branch=form.bank_branch.data or None,
                bank_account_number=form.bank_account_number.data or None,
                bank_code=form.bank_code.data or None,
                swift_code=form.swift_code.data or None,
            )
            db.session.add(emp)
            db.session.commit()
            log_create('Employee', emp.id, model_to_audit_dict(emp), user_id=current_user.id, description='Employee created')
            flash('Employee created successfully.', 'success')
            return redirect(url_for('employees.view', id=emp.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Could not save employee: {str(e)}', 'danger')
    if request.method == 'POST' and form.errors:
        flash('Please fix the errors below.', 'danger')
    return render_template('employees/create.html', form=form)


@employees_bp.route('/<int:id>')
@login_required
def view(id):
    emp = db.session.get(Employee, id)
    if not emp:
        from flask import abort
        abort(404)
    # Employees can view own profile; others need permission
    if (current_user.employee_id or 0) != emp.id and not current_user.has_permission('view_employees'):
        from flask import abort
        abort(403)
    return render_template('employees/view.html', employee=emp)


@employees_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def edit(id):
    emp = db.session.get(Employee, id)
    if not emp:
        from flask import abort
        abort(404)
    form = EmployeeForm(obj=emp)
    form.department_id.choices = [('', '--')] + [(d.id, d.name) for d in db.session.query(Department).order_by(Department.name).all()]
    form.job_title_id.choices = [('', '--')] + [(j.id, j.name) for j in db.session.query(JobTitle).order_by(JobTitle.name).all()]
    form.manager_id.choices = [('', '--')] + [(e.id, e.full_name) for e in db.session.query(Employee).filter(Employee.status == 'active').order_by(Employee.first_name).all()]
    if form.validate_on_submit():
        old = model_to_audit_dict(emp)
        emp.first_name = form.first_name.data
        emp.last_name = form.last_name.data
        emp.middle_name = form.middle_name.data or None
        emp.date_of_birth = form.date_of_birth.data
        emp.gender = form.gender.data or None
        emp.marital_status = form.marital_status.data or None
        emp.nationality = form.nationality.data or None
        emp.national_id = form.national_id.data or None
        emp.passport_number = form.passport_number.data or None
        emp.kra_pin = form.kra_pin.data or None
        emp.nssf_number = form.nssf_number.data or None
        emp.nhif_number = form.nhif_number.data or None
        emp.email = form.email.data or None
        emp.phone = normalize_phone_ke(form.phone.data) if form.phone.data else None
        emp.phone_alt = normalize_phone_ke(form.phone_alt.data) if form.phone_alt.data else None
        emp.address = form.address.data or None
        emp.postal_address = form.postal_address.data or None
        emp.emergency_contact_name = form.emergency_contact_name.data or None
        emp.emergency_contact_phone = form.emergency_contact_phone.data or None
        emp.department_id = form.department_id.data or None
        emp.job_title_id = form.job_title_id.data or None
        emp.manager_id = form.manager_id.data or None
        emp.status = form.status.data
        emp.employment_type = form.employment_type.data or None
        emp.hire_date = form.hire_date.data
        emp.probation_end_date = form.probation_end_date.data
        emp.confirmation_date = form.confirmation_date.data
        emp.contract_end_date = form.contract_end_date.data
        emp.bank_name = form.bank_name.data or None
        emp.bank_branch = form.bank_branch.data or None
        emp.bank_account_number = form.bank_account_number.data or None
        emp.bank_code = form.bank_code.data or None
        emp.swift_code = form.swift_code.data or None
        db.session.commit()
        log_update('Employee', emp.id, old, model_to_audit_dict(emp), user_id=current_user.id, description='Employee updated')
        flash('Employee updated.', 'success')
        return redirect(url_for('employees.view', id=emp.id))
    return render_template('employees/edit.html', form=form, employee=emp)


@employees_bp.route('/<int:id>/salary', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def salary(id):
    from datetime import date
    emp = db.session.get(Employee, id)
    if not emp:
        from flask import abort
        abort(404)
    form = EmployeeSalaryForm()
    salary_records = db.session.query(EmployeeSalary).filter(EmployeeSalary.employee_id == id).order_by(
        EmployeeSalary.effective_from.desc()).all()
    allowances = db.session.query(Allowance).order_by(Allowance.name).all()
    employee_allowances = db.session.query(EmployeeAllowance).filter(EmployeeAllowance.employee_id == id).order_by(
        EmployeeAllowance.effective_from.desc()).all()

    if request.method == 'POST':
        action = request.form.get('action', 'add_salary')
        if action == 'add_salary' and form.validate_on_submit():
            rec = EmployeeSalary(
                employee_id=id,
                effective_from=form.effective_from.data,
                basic_salary=form.basic_salary.data,
                house_allowance=0,
                transport_allowance=0,
                meal_allowance=0,
                other_allowances=0,
                pension_employee_percent=form.pension_employee_percent.data or None,
                pension_employer_percent=form.pension_employer_percent.data or None,
                notes=form.notes.data or None,
            )
            db.session.add(rec)
            db.session.commit()
            flash('Salary record added.', 'success')
            return redirect(url_for('employees.salary', id=id))
        if action == 'add_allowance':
            allowance_id = request.form.get('allowance_id', type=int)
            amount = request.form.get('amount', type=float)
            eff_from = request.form.get('effective_from')
            if allowance_id and amount is not None and amount >= 0 and eff_from:
                try:
                    from datetime import datetime
                    eff_date = datetime.strptime(eff_from, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    flash('Invalid effective date.', 'danger')
                else:
                    a = db.session.get(Allowance, allowance_id)
                    if a:
                        ea = EmployeeAllowance(
                            employee_id=id,
                            allowance_id=allowance_id,
                            amount=amount,
                            effective_from=eff_date,
                        )
                        db.session.add(ea)
                        db.session.commit()
                        flash(f'{a.name} allowance added.', 'success')
                    else:
                        flash('Allowance not found.', 'danger')
            else:
                flash('Select an allowance, amount and effective date.', 'danger')
            return redirect(url_for('employees.salary', id=id))
        if action == 'end_allowance':
            ea_id = request.form.get('employee_allowance_id', type=int)
            if ea_id:
                ea = db.session.query(EmployeeAllowance).filter(
                    EmployeeAllowance.id == ea_id,
                    EmployeeAllowance.employee_id == id,
                ).first()
                if ea and ea.effective_to is None:
                    ea.effective_to = date.today()
                    db.session.commit()
                    flash('Allowance ended.', 'success')
            return redirect(url_for('employees.salary', id=id))

    return render_template(
        'employees/salary.html',
        employee=emp,
        form=form,
        salary_records=salary_records,
        allowances=allowances,
        employee_allowances=employee_allowances,
    )


@employees_bp.route('/<int:id>/deductions', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def employee_deductions(id):
    """Recurring / loan-style deductions for payroll (applied every month while active)."""
    from datetime import datetime
    from decimal import Decimal as Dec

    emp = db.session.get(Employee, id)
    if not emp:
        from flask import abort
        abort(404)
    assignments = (
        db.session.query(EmployeeDeduction)
        .filter(EmployeeDeduction.employee_id == id)
        .order_by(EmployeeDeduction.effective_from.desc())
        .all()
    )
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            title = (request.form.get('title') or '').strip()
            mode = (request.form.get('calculation_mode') or 'fixed').strip()
            eff_from_s = request.form.get('effective_from')
            eff_to_s = (request.form.get('effective_to') or '').strip() or None
            amount = request.form.get('amount', type=float)
            rate = request.form.get('rate_percent', type=float)
            bal_s = (request.form.get('remaining_balance') or '').strip() or None
            notes = (request.form.get('notes') or '').strip() or None
            if title and eff_from_s:
                try:
                    eff_from = datetime.strptime(eff_from_s, '%Y-%m-%d').date()
                except ValueError:
                    flash('Invalid effective from date.', 'danger')
                    return redirect(url_for('employees.employee_deductions', id=id))
                eff_to = None
                if eff_to_s:
                    try:
                        eff_to = datetime.strptime(eff_to_s, '%Y-%m-%d').date()
                    except ValueError:
                        flash('Invalid effective to date.', 'danger')
                        return redirect(url_for('employees.employee_deductions', id=id))
                db.session.add(
                    EmployeeDeduction(
                        employee_id=id,
                        deduction_id=None,
                        title=title[:200],
                        calculation_mode=mode,
                        amount=Dec(str(amount or 0)),
                        rate_percent=Dec(str(rate)) if rate is not None else None,
                        effective_from=eff_from,
                        effective_to=eff_to,
                        remaining_balance=Dec(str(bal_s)) if bal_s else None,
                        notes=notes,
                        is_active=True,
                    )
                )
                db.session.commit()
                flash('Deduction added.', 'success')
            else:
                flash('Enter a title / description and effective from date.', 'danger')
        elif action == 'delete':
            aid = request.form.get('assignment_id', type=int)
            if aid:
                row = (
                    db.session.query(EmployeeDeduction)
                    .filter(EmployeeDeduction.id == aid, EmployeeDeduction.employee_id == id)
                    .first()
                )
                if row:
                    db.session.delete(row)
                    db.session.commit()
                    flash('Deduction removed.', 'success')
        return redirect(url_for('employees.employee_deductions', id=id))
    return render_template(
        'employees/deductions.html',
        employee=emp,
        assignments=assignments,
    )


@employees_bp.route('/<int:id>/link-user', methods=['GET', 'POST'])
@login_required
@permission_required('edit_employees')
def link_user(id):
    emp = db.session.get(Employee, id)
    if not emp:
        from flask import abort
        abort(404)
    if emp.user:
        flash('This employee already has a linked login account.', 'info')
        return redirect(url_for('employees.view', id=id))
    roles = db.session.query(Role).order_by(Role.name).all()
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        role_id = request.form.get('role_id', type=int)
        if not email:
            flash('Email is required.', 'danger')
            return render_template('employees/link_user.html', employee=emp, roles=roles)
        if not password or len(password) < current_app.config.get('PASSWORD_MIN_LENGTH', 8):
            flash(f'Password must be at least {current_app.config.get("PASSWORD_MIN_LENGTH", 8)} characters.', 'danger')
            return render_template('employees/link_user.html', employee=emp, roles=roles)
        if db.session.query(User).filter_by(email=email).first():
            flash('A user with this email already exists.', 'danger')
            return render_template('employees/link_user.html', employee=emp, roles=roles)
        user = User(email=email, employee_id=emp.id, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        if role_id:
            role = db.session.get(Role, role_id)
            if role:
                db.session.add(UserRole(user_id=user.id, role_id=role.id))
        db.session.commit()
        flash('Login account created and linked to this employee.', 'success')
        return redirect(url_for('employees.view', id=id))
    return render_template('employees/link_user.html', employee=emp, roles=roles)


def _allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in current_app.config.get('ALLOWED_EXTENSIONS', {'pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'})


def _can_access_employee_documents(employee_id: int) -> bool:
    """HR can access any docs; employees can access their own."""
    if current_user.has_permission('edit_employees'):
        return True
    return bool(current_user.employee_id and int(current_user.employee_id) == int(employee_id))


def _cloudinary_enabled() -> bool:
    return bool(
        cloudinary
        and current_app.config.get('CLOUDINARY_CLOUD_NAME')
        and current_app.config.get('CLOUDINARY_API_KEY')
        and current_app.config.get('CLOUDINARY_API_SECRET')
    )


def _configure_cloudinary():
    if not _cloudinary_enabled():
        return
    cloudinary.config(
        cloud_name=current_app.config.get('CLOUDINARY_CLOUD_NAME'),
        api_key=current_app.config.get('CLOUDINARY_API_KEY'),
        api_secret=current_app.config.get('CLOUDINARY_API_SECRET'),
        secure=True,
    )


def _cloudinary_upload_employee_doc(file_storage, employee_id: int) -> tuple[str, int]:
    """
    Upload document to Cloudinary and return (stored_reference, size_bytes).
    stored_reference format: cld::<resource_type>::<public_id>
    """
    _configure_cloudinary()
    original = secure_filename(file_storage.filename or 'document')
    upload_res = cloudinary.uploader.upload(
        file_storage,
        resource_type='auto',
        folder=current_app.config.get('CLOUDINARY_DOCS_FOLDER', 'hrms/employee_docs'),
        public_id=f"employee_{employee_id}_{os.urandom(4).hex()}_{os.path.splitext(original)[0]}",
        overwrite=False,
        use_filename=False,
    )
    public_id = upload_res.get('public_id')
    resource_type = upload_res.get('resource_type', 'raw')
    size_bytes = int(upload_res.get('bytes') or 0)
    if not public_id:
        raise ValueError('Cloudinary upload did not return a public_id.')
    return f"cld::{resource_type}::{public_id}", size_bytes


@employees_bp.route('/<int:id>/documents', methods=['GET', 'POST'])
@login_required
def documents(id):
    emp = db.session.get(Employee, id)
    if not emp:
        abort(404)
    if not _can_access_employee_documents(id):
        abort(403)
    docs = db.session.query(EmployeeDocument).filter(EmployeeDocument.employee_id == id).order_by(
        EmployeeDocument.created_at.desc()).all()
    categories = db.session.query(DocumentCategory).order_by(DocumentCategory.name).all()
    if not categories:
        for code, name in [('CONTRACT', 'Contract'), ('ID', 'National ID'), ('KRA_PIN', 'KRA PIN'),
                           ('NSSF', 'NSSF'), ('CERTIFICATE', 'Certificate'), ('OTHER', 'Other')]:
            db.session.add(DocumentCategory(code=code, name=name, track_expiry=(code in ('CONTRACT', 'ID', 'CERTIFICATE'))))
        db.session.commit()
        categories = db.session.query(DocumentCategory).order_by(DocumentCategory.name).all()
    if request.method == 'POST':
        if not current_user.has_permission('edit_employees'):
            abort(403)
        name = (request.form.get('name') or '').strip() or 'Document'
        category_id = request.form.get('category_id', type=int) or None
        notes = (request.form.get('notes') or '').strip() or None
        f = request.files.get('file')
        if not f or not f.filename:
            flash('Please select a file to upload.', 'danger')
            return redirect(url_for('employees.documents', id=id))
        if not _allowed_file(f.filename):
            flash('File type not allowed. Use PDF, DOC, DOCX, JPG, PNG.', 'danger')
            return redirect(url_for('employees.documents', id=id))
        file_path = ''
        size_bytes = None
        if _cloudinary_enabled():
            try:
                file_path, size_bytes = _cloudinary_upload_employee_doc(f, id)
            except Exception:
                current_app.logger.exception('Cloudinary upload failed; falling back to local storage.')
                # reset stream pointer in case cloud upload consumed it
                try:
                    f.stream.seek(0)
                except Exception:
                    pass
        if not file_path:
            upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'employee_docs', str(id))
            os.makedirs(upload_dir, exist_ok=True)
            filename = secure_filename(f.filename)
            base, ext = os.path.splitext(filename)
            unique = f"{base}_{os.urandom(4).hex()}{ext}"
            file_path = os.path.join('employee_docs', str(id), unique)
            full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_path)
            f.save(full_path)
            size_bytes = os.path.getsize(full_path)
        doc = EmployeeDocument(
            employee_id=id,
            category_id=category_id,
            name=name,
            file_path=file_path.replace('\\', '/'),
            file_size=size_bytes,
            notes=notes,
        )
        db.session.add(doc)
        db.session.commit()
        flash('Document uploaded.', 'success')
        return redirect(url_for('employees.documents', id=id))
    return render_template('employees/documents.html', employee=emp, documents=docs, categories=categories)


@employees_bp.route('/<int:id>/documents/<int:doc_id>/open')
@login_required
def document_open(id, doc_id):
    """Open/download employee document."""
    if not _can_access_employee_documents(id):
        abort(403)
    doc = db.session.get(EmployeeDocument, doc_id)
    if not doc or doc.employee_id != id:
        abort(404)
    rel_path = (doc.file_path or '').replace('\\', '/').lstrip('/').strip()
    if not rel_path:
        abort(404)
    # Cloudinary-backed reference
    if rel_path.startswith('cld::'):
        parts = rel_path.split('::', 2)
        if len(parts) != 3 or not cloudinary_url:
            abort(404)
        _prefix, resource_type, public_id = parts
        flags = 'attachment' if request.args.get('download') in {'1', 'true', 'yes'} else None
        file_url, _ = cloudinary_url(
            public_id,
            resource_type=resource_type or 'raw',
            secure=True,
            flags=flags,
        )
        return redirect(file_url)
    # Backward compatibility: if direct URL was stored, redirect it.
    if rel_path.startswith('http://') or rel_path.startswith('https://'):
        return redirect(rel_path)
    upload_root = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(upload_root, rel_path))
    if not full_path.startswith(upload_root + os.sep):
        abort(403)
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        flash('Document file is missing from storage.', 'danger')
        return redirect(url_for('employees.documents', id=id))
    download = request.args.get('download') in {'1', 'true', 'yes'}
    mime, _ = mimetypes.guess_type(full_path)
    return send_file(
        full_path,
        mimetype=mime or 'application/octet-stream',
        as_attachment=download,
        download_name=os.path.basename(full_path),
    )
