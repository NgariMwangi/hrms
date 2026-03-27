"""Statutory rate configuration (PAYE, NSSF, SHIF, Housing Levy)."""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app.extensions import db
from app.models.statutory import StatutoryRate, PayeBracket, NssfTier
from app.forms.settings_forms import StatutoryRateForm, PayeBracketForm
from app.decorators.permissions import permission_required
from datetime import date

statutory_bp = Blueprint('statutory', __name__)


@statutory_bp.route('/')
@login_required
@permission_required('manage_statutory')
def index():
    rates = db.session.query(StatutoryRate).order_by(StatutoryRate.code, StatutoryRate.effective_from.desc()).all()
    brackets = db.session.query(PayeBracket).order_by(PayeBracket.effective_from.desc(), PayeBracket.bracket_order).all()
    tiers = db.session.query(NssfTier).order_by(NssfTier.effective_from.desc(), NssfTier.tier_number).all()
    return render_template('statutory/index.html', rates=rates, brackets=brackets, tiers=tiers)


@statutory_bp.route('/rate/add', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def rate_add():
    form = StatutoryRateForm()
    if form.validate_on_submit():
        r = StatutoryRate(
            code=form.code.data,
            effective_from=form.effective_from.data,
            effective_to=form.effective_to.data,
            value=form.value.data,
            description=form.description.data,
        )
        db.session.add(r)
        db.session.commit()
        flash('Rate added.', 'success')
        return redirect(url_for('statutory.index'))
    return render_template('statutory/rate_form.html', form=form, rate=None)


@statutory_bp.route('/rate/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def rate_edit(id):
    r = db.session.get(StatutoryRate, id)
    if not r:
        flash('Rate not found.', 'danger')
        return redirect(url_for('statutory.index'))
    form = StatutoryRateForm()
    if form.validate_on_submit():
        r.code = form.code.data
        r.effective_from = form.effective_from.data
        r.effective_to = form.effective_to.data
        r.value = form.value.data
        r.description = form.description.data
        db.session.commit()
        flash('Rate updated.', 'success')
        return redirect(url_for('statutory.index'))
    if request.method == 'GET':
        form.code.data = r.code
        form.effective_from.data = r.effective_from
        form.effective_to.data = r.effective_to
        form.value.data = float(r.value) if r.value is not None else None
        form.description.data = r.description or ''
    return render_template('statutory/rate_form.html', form=form, rate=r)


@statutory_bp.route('/rate/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_statutory')
def rate_delete(id):
    r = db.session.get(StatutoryRate, id)
    if not r:
        flash('Rate not found.', 'danger')
        return redirect(url_for('statutory.index'))
    db.session.delete(r)
    db.session.commit()
    flash('Rate deleted.', 'success')
    return redirect(url_for('statutory.index'))


@statutory_bp.route('/paye/add', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def paye_add():
    form = PayeBracketForm()
    if form.validate_on_submit():
        b = PayeBracket(
            effective_from=form.effective_from.data,
            effective_to=form.effective_to.data,
            bracket_order=form.bracket_order.data,
            min_amount=form.min_amount.data,
            max_amount=form.max_amount.data,
            rate_percent=form.rate_percent.data,
        )
        db.session.add(b)
        db.session.commit()
        flash('PAYE bracket added.', 'success')
        return redirect(url_for('statutory.index'))
    if request.method == 'POST' and form.errors:
        flash('Please fix the highlighted PAYE form errors.', 'danger')
    return render_template('statutory/paye_form.html', form=form, bracket=None)


@statutory_bp.route('/paye/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('manage_statutory')
def paye_edit(id):
    b = db.session.get(PayeBracket, id)
    if not b:
        flash('PAYE bracket not found.', 'danger')
        return redirect(url_for('statutory.index'))
    form = PayeBracketForm()
    if form.validate_on_submit():
        b.effective_from = form.effective_from.data
        b.effective_to = form.effective_to.data
        b.bracket_order = form.bracket_order.data
        b.min_amount = form.min_amount.data
        b.max_amount = form.max_amount.data
        b.rate_percent = form.rate_percent.data
        db.session.commit()
        flash('PAYE bracket updated.', 'success')
        return redirect(url_for('statutory.index'))
    if request.method == 'POST' and form.errors:
        flash('Please fix the highlighted PAYE form errors.', 'danger')
    if request.method == 'GET':
        form.effective_from.data = b.effective_from
        form.effective_to.data = b.effective_to
        form.bracket_order.data = b.bracket_order
        form.min_amount.data = float(b.min_amount) if b.min_amount is not None else None
        form.max_amount.data = float(b.max_amount) if b.max_amount is not None else None
        form.rate_percent.data = float(b.rate_percent) if b.rate_percent is not None else None
    return render_template('statutory/paye_form.html', form=form, bracket=b)


@statutory_bp.route('/paye/<int:id>/delete', methods=['POST'])
@login_required
@permission_required('manage_statutory')
def paye_delete(id):
    b = db.session.get(PayeBracket, id)
    if not b:
        flash('PAYE bracket not found.', 'danger')
        return redirect(url_for('statutory.index'))
    db.session.delete(b)
    db.session.commit()
    flash('PAYE bracket deleted.', 'success')
    return redirect(url_for('statutory.index'))
