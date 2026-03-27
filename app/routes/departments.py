"""Department management."""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app.extensions import db
from app.models.department import Department
from app.forms.department_forms import DepartmentForm
from app.decorators.permissions import permission_required

departments_bp = Blueprint('departments', __name__)


def _department_choices(exclude_id=None):
    """Choices for parent department: empty + all departments (optionally exclude one to avoid self-reference)."""
    q = db.session.query(Department).order_by(Department.name)
    if exclude_id is not None:
        q = q.filter(Department.id != exclude_id)
    return [('', '-- None --')] + [(d.id, d.name) for d in q.all()]


@departments_bp.route('/')
@login_required
@permission_required('view_departments')
def index():
    departments = db.session.query(Department).order_by(Department.name).all()
    return render_template('departments/index.html', departments=departments)


@departments_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_departments')
def create():
    form = DepartmentForm()
    form.parent_id.choices = _department_choices()
    if form.validate_on_submit():
        existing = db.session.query(Department).filter_by(code=form.code.data.strip().upper()).first()
        if existing:
            flash('A department with this code already exists.', 'danger')
            return render_template('departments/create.html', form=form)
        dept = Department(
            code=form.code.data.strip().upper(),
            name=form.name.data.strip(),
            description=form.description.data.strip() or None,
            parent_id=form.parent_id.data,
        )
        db.session.add(dept)
        db.session.commit()
        flash('Department created.', 'success')
        return redirect(url_for('departments.index'))
    return render_template('departments/create.html', form=form)


@departments_bp.route('/<int:id>')
@login_required
@permission_required('view_departments')
def view(id):
    dept = db.session.get(Department, id)
    if dept is None:
        flash('Department not found.', 'danger')
        return redirect(url_for('departments.index'))
    employee_count = len(dept.employees) if dept.employees else 0
    return render_template('departments/view.html', department=dept, employee_count=employee_count)


@departments_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_departments')
def edit(id):
    dept = db.session.get(Department, id)
    if dept is None:
        flash('Department not found.', 'danger')
        return redirect(url_for('departments.index'))
    form = DepartmentForm()
    form.parent_id.choices = _department_choices(exclude_id=id)
    if form.validate_on_submit():
        existing = db.session.query(Department).filter(
            Department.code == form.code.data.strip().upper(),
            Department.id != id,
        ).first()
        if existing:
            flash('A department with this code already exists.', 'danger')
            return render_template('departments/edit.html', form=form, department=dept)
        dept.code = form.code.data.strip().upper()
        dept.name = form.name.data.strip()
        dept.description = form.description.data.strip() or None
        dept.parent_id = form.parent_id.data
        db.session.commit()
        flash('Department updated.', 'success')
        return redirect(url_for('departments.view', id=dept.id))
    if request.method == 'GET':
        form.code.data = dept.code
        form.name.data = dept.name
        form.description.data = dept.description or ''
        form.parent_id.data = dept.parent_id
    return render_template('departments/edit.html', form=form, department=dept)
