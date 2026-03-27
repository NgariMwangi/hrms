"""Leave requests and approvals."""
from decimal import Decimal

from flask import Blueprint, abort, jsonify, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models.leave import LeaveBalance, LeaveRequest, LeaveType
from app.services.leave_stats_service import statistics_for_employee
from app.forms.leave_forms import LeaveRequestForm, LeaveApprovalForm, LeaveTypeForm
from app.decorators.permissions import permission_required
from app.utils.date_helpers import (
    approved_leave_remaining_days,
    end_date_for_inclusive_leave_days,
    leave_days_between,
)
from datetime import date, datetime
from sqlalchemy.orm import joinedload

leave_bp = Blueprint('leave', __name__)


def _apply_leave_type_form(form: LeaveTypeForm, lt: LeaveType) -> None:
    lt.code = form.code.data.strip().upper()
    lt.name = form.name.data.strip()
    lt.days_per_year = form.days_per_year.data if form.days_per_year.data is not None else None
    lt.accrues_monthly = bool(form.accrues_monthly.data)
    lt.days_per_month = form.days_per_month.data if form.days_per_month.data is not None else None
    lt.requires_approval = bool(form.requires_approval.data)
    lt.requires_document = bool(form.requires_document.data)
    lt.is_paid = bool(form.is_paid.data)
    lt.min_days_request = form.min_days_request.data if form.min_days_request.data is not None else Decimal('0.5')
    lt.max_consecutive_days = form.max_consecutive_days.data
    lt.carry_forward_max = form.carry_forward_max.data if form.carry_forward_max.data is not None else 0
    lt.is_active = bool(form.is_active.data)
    basis = (form.days_count_basis.data or 'working').strip().lower()
    lt.days_count_basis = basis if basis in ('working', 'calendar') else 'working'


@leave_bp.route('/')
@login_required
def index():
    """Leave list - my requests or all (for HR/manager)."""
    q = db.session.query(LeaveRequest).options(
        joinedload(LeaveRequest.leave_type),
        joinedload(LeaveRequest.employee),
    )
    if current_user.has_permission('approve_leave'):
        requests = q.order_by(LeaveRequest.created_at.desc()).all()
    else:
        emp_id = current_user.employee_id
        if not emp_id:
            requests = []
        else:
            requests = q.filter(LeaveRequest.employee_id == emp_id).order_by(LeaveRequest.created_at.desc()).all()
    today = date.today()
    remaining_days = {}
    for r in requests:
        if r.status != 'approved' or not r.leave_type or not r.start_date or not r.end_date:
            remaining_days[r.id] = None
            continue
        basis = (r.leave_type.days_count_basis or 'working').lower()
        if basis not in ('working', 'calendar'):
            basis = 'working'
        remaining_days[r.id] = approved_leave_remaining_days(
            r.start_date, r.end_date, basis, today=today
        )
    leave_statistics = None
    stats_year = today.year
    if current_user.employee_id:
        leave_statistics = statistics_for_employee(current_user.employee_id, stats_year)
    return render_template(
        'leave/requests.html',
        requests=requests,
        remaining_days=remaining_days,
        leave_statistics=leave_statistics,
        stats_year=stats_year,
    )


@leave_bp.route('/request', methods=['GET', 'POST'])
@login_required
def request_leave():
    form = LeaveRequestForm()
    form.leave_type_id.choices = [(lt.id, lt.name) for lt in db.session.query(LeaveType).filter(LeaveType.is_active == True).order_by(LeaveType.name).all()]
    if form.validate_on_submit():
        emp_id = current_user.employee_id
        if not emp_id:
            flash('No employee linked to your account. Contact HR.', 'warning')
            return render_template('leave/my_requests.html', form=form)
        lt = db.session.get(LeaveType, form.leave_type_id.data)
        if not lt:
            flash('Invalid leave type.', 'danger')
            return render_template('leave/my_requests.html', form=form)
        basis = (lt.days_count_basis or 'working').lower()
        if basis not in ('working', 'calendar'):
            basis = 'working'
        days_requested = Decimal(
            str(
                leave_days_between(
                    form.start_date.data,
                    form.end_date.data,
                    basis,
                )
            )
        )
        lr = LeaveRequest(
            employee_id=emp_id,
            leave_type_id=form.leave_type_id.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            days_requested=days_requested,
            reason=form.reason.data,
            status='pending',
        )
        db.session.add(lr)
        db.session.commit()
        flash('Leave request submitted.', 'success')
        return redirect(url_for('leave.index'))
    return render_template('leave/my_requests.html', form=form)


@leave_bp.route('/api/suggest-end-date')
@login_required
def suggest_end_date():
    """
    Given leave type + start date, return suggested end date for the full entitlement
    (days_per_year) using that type's day-count basis — helps maternity / paternity planning.
    """
    leave_type_id = request.args.get('leave_type_id', type=int)
    start_raw = request.args.get('start_date')
    if not leave_type_id or not start_raw:
        return jsonify({'error': 'leave_type_id and start_date are required'}), 400
    lt = db.session.get(LeaveType, leave_type_id)
    if not lt or not lt.is_active:
        return jsonify({'error': 'Invalid leave type'}), 404
    try:
        start = date.fromisoformat(start_raw)
    except ValueError:
        return jsonify({'error': 'Invalid start_date (use YYYY-MM-DD)'}), 400
    entitlement = lt.days_per_year
    if entitlement is None or Decimal(str(entitlement)) <= 0:
        return jsonify({'suggest': False, 'message': 'This leave type has no fixed days-per-year entitlement.'})
    # Whole days for period end (90, 14, 21 — not fractional half-days)
    total = int(Decimal(str(entitlement)).quantize(Decimal('1')))
    basis = (lt.days_count_basis or 'working').lower()
    if basis not in ('working', 'calendar'):
        basis = 'working'
    end = end_date_for_inclusive_leave_days(start, total, basis)
    basis_label = 'calendar days (including weekends)' if basis == 'calendar' else 'working days (Mon–Fri)'
    return jsonify(
        {
            'suggest': True,
            'leave_type_code': lt.code,
            'leave_type_name': lt.name,
            'total_days': total,
            'basis': basis,
            'basis_label': basis_label,
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),
            'end_date_display': end.strftime('%d %b %Y'),
        }
    )


@leave_bp.route('/<int:id>/approve', methods=['GET', 'POST'])
@login_required
@permission_required('approve_leave')
def approve(id):
    lr = db.session.get(LeaveRequest, id)
    if not lr or lr.status != 'pending':
        from flask import abort
        abort(404)
    form = LeaveApprovalForm()
    if form.validate_on_submit():
        lr.status = 'approved' if form.action.data == 'approve' else 'rejected'
        lr.reviewed_by_id = current_user.id
        lr.reviewed_at = datetime.utcnow()
        lr.review_notes = form.review_notes.data
        db.session.commit()
        flash('Leave request updated.', 'success')
        return redirect(url_for('leave.index'))
    return render_template('leave/approve.html', request=lr, form=form)


@leave_bp.route('/types')
@login_required
@permission_required('manage_leave_types')
def types_index():
    """HR: list leave categories (annual, sick, etc.)."""
    types_list = db.session.query(LeaveType).order_by(LeaveType.name).all()
    return render_template('leave/types.html', types_list=types_list)


@leave_bp.route('/types/create', methods=['GET', 'POST'])
@login_required
@permission_required('manage_leave_types')
def type_create():
    form = LeaveTypeForm()
    if form.validate_on_submit():
        code = form.code.data.strip().upper()
        if db.session.query(LeaveType).filter_by(code=code).first():
            flash('A leave type with this code already exists.', 'danger')
            return render_template('leave/type_form.html', form=form, leave_type=None)
        lt = LeaveType()
        _apply_leave_type_form(form, lt)
        db.session.add(lt)
        db.session.commit()
        flash('Leave type created.', 'success')
        return redirect(url_for('leave.types_index'))
    return render_template('leave/type_form.html', form=form, leave_type=None)


@leave_bp.route('/types/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_leave_types')
def type_edit(id):
    lt = db.session.get(LeaveType, id)
    if not lt:
        abort(404)
    form = LeaveTypeForm()
    if form.validate_on_submit():
        code = form.code.data.strip().upper()
        existing = db.session.query(LeaveType).filter(LeaveType.code == code, LeaveType.id != id).first()
        if existing:
            flash('Another leave type already uses this code.', 'danger')
            return render_template('leave/type_form.html', form=form, leave_type=lt)
        _apply_leave_type_form(form, lt)
        db.session.commit()
        flash('Leave type updated.', 'success')
        return redirect(url_for('leave.types_index'))
    if request.method == 'GET':
        form.code.data = lt.code
        form.name.data = lt.name
        form.days_per_year.data = lt.days_per_year
        form.accrues_monthly.data = lt.accrues_monthly
        form.days_per_month.data = lt.days_per_month
        form.requires_approval.data = lt.requires_approval
        form.requires_document.data = lt.requires_document
        form.is_paid.data = lt.is_paid
        form.min_days_request.data = lt.min_days_request
        form.max_consecutive_days.data = lt.max_consecutive_days
        form.carry_forward_max.data = lt.carry_forward_max
        form.is_active.data = lt.is_active
        form.days_count_basis.data = lt.days_count_basis or 'working'
    return render_template('leave/type_form.html', form=form, leave_type=lt)


@leave_bp.route('/types/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_leave_types')
def type_delete(id):
    lt = db.session.get(LeaveType, id)
    if not lt:
        flash('Leave type not found.', 'danger')
        return redirect(url_for('leave.types_index'))
    n_requests = (
        db.session.query(func.count(LeaveRequest.id))
        .filter(LeaveRequest.leave_type_id == id)
        .scalar()
    )
    n_balances = (
        db.session.query(func.count(LeaveBalance.id))
        .filter(LeaveBalance.leave_type_id == id)
        .scalar()
    )
    if (n_requests or 0) > 0:
        flash(
            'Cannot delete this leave type: it has leave requests on file. '
            'Deactivate it instead (set Active to No on edit).',
            'warning',
        )
        return redirect(url_for('leave.types_index'))
    if (n_balances or 0) > 0:
        flash(
            'Cannot delete this leave type: employee leave balances exist for it. '
            'Clear or adjust balances first, or deactivate the type.',
            'warning',
        )
        return redirect(url_for('leave.types_index'))
    name = lt.name
    db.session.delete(lt)
    db.session.commit()
    flash(f'Leave type "{name}" was deleted.', 'success')
    return redirect(url_for('leave.types_index'))
