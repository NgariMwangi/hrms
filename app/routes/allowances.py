"""Allowance type management (company-wide)."""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app.extensions import db
from app.models.payroll import Allowance
from app.forms.allowance_forms import AllowanceForm
from app.decorators.permissions import permission_required

allowances_bp = Blueprint('allowances', __name__)


@allowances_bp.route('/')
@login_required
@permission_required('view_departments')
def index():
    allowances = db.session.query(Allowance).order_by(Allowance.name).all()
    return render_template('allowances/index.html', allowances=allowances)


@allowances_bp.route('/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_departments')
def create():
    form = AllowanceForm()
    if form.validate_on_submit():
        existing = db.session.query(Allowance).filter_by(code=form.code.data.strip().upper()).first()
        if existing:
            flash('An allowance with this code already exists.', 'danger')
            return render_template('allowances/create.html', form=form)
        a = Allowance(
            code=form.code.data.strip().upper(),
            name=form.name.data.strip(),
            description=form.description.data.strip() or None,
            is_taxable=form.is_taxable.data,
            is_pensionable=form.is_pensionable.data,
        )
        db.session.add(a)
        db.session.commit()
        flash('Allowance created.', 'success')
        return redirect(url_for('allowances.index'))
    return render_template('allowances/create.html', form=form)


@allowances_bp.route('/<int:id>')
@login_required
@permission_required('view_departments')
def view(id):
    a = db.session.get(Allowance, id)
    if a is None:
        flash('Allowance not found.', 'danger')
        return redirect(url_for('allowances.index'))
    return render_template('allowances/view.html', allowance=a)


@allowances_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_departments')
def edit(id):
    a = db.session.get(Allowance, id)
    if a is None:
        flash('Allowance not found.', 'danger')
        return redirect(url_for('allowances.index'))
    form = AllowanceForm()
    if form.validate_on_submit():
        existing = db.session.query(Allowance).filter(
            Allowance.code == form.code.data.strip().upper(),
            Allowance.id != id,
        ).first()
        if existing:
            flash('An allowance with this code already exists.', 'danger')
            return render_template('allowances/edit.html', form=form, allowance=a)
        a.code = form.code.data.strip().upper()
        a.name = form.name.data.strip()
        a.description = form.description.data.strip() or None
        a.is_taxable = form.is_taxable.data
        a.is_pensionable = form.is_pensionable.data
        db.session.commit()
        flash('Allowance updated.', 'success')
        return redirect(url_for('allowances.view', id=a.id))
    if request.method == 'GET':
        form.code.data = a.code
        form.name.data = a.name
        form.description.data = a.description or ''
        form.is_taxable.data = a.is_taxable
        form.is_pensionable.data = a.is_pensionable
    return render_template('allowances/edit.html', form=form, allowance=a)


@allowances_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_departments')
def delete(id):
    a = db.session.get(Allowance, id)
    if a is None:
        flash('Allowance not found.', 'danger')
        return redirect(url_for('allowances.index'))
    count = a.employee_allowances.count()
    if count > 0:
        flash(f'Cannot delete: this allowance is used by {count} employee assignment(s). Remove them first.', 'danger')
        return redirect(url_for('allowances.view', id=id))
    db.session.delete(a)
    db.session.commit()
    flash('Allowance deleted.', 'success')
    return redirect(url_for('allowances.index'))
