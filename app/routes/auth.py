"""Authentication: login, logout, password reset."""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user, login_required
from app.extensions import db, limiter
from app.models.user import User, Role, UserRole
from app.forms.auth_forms import LoginForm, RegisterForm, ForgotPasswordForm, ResetPasswordForm
from app.services.audit_service import log_login, log_audit

auth_bp = Blueprint('auth', __name__)


def _allow_registration():
    """Registration is only allowed when no users exist (first-time setup)."""
    return db.session.query(User).count() == 0


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.query(User).filter_by(email=form.email.data.strip().lower()).first()
        if user is None:
            log_audit('LOGIN_FAILED', record_type='User', record_id=None,
                      new_values={'email': form.email.data}, description='Login failed - user not found')
            flash('Invalid email or password.', 'danger')
            return render_template('auth/login.html', form=form)
        if user.is_locked:
            flash('Account temporarily locked. Try again later.', 'warning')
            return render_template('auth/login.html', form=form)
        if not user.check_password(form.password.data):
            user.failed_login_count = (user.failed_login_count or 0) + 1
            from flask import current_app
            if user.failed_login_count >= current_app.config.get('ACCOUNT_LOCKOUT_ATTEMPTS', 5):
                user.locked_until = datetime.utcnow() + timedelta(
                    minutes=current_app.config.get('ACCOUNT_LOCKOUT_DURATION_MINUTES', 15))
            db.session.commit()
            log_audit('LOGIN_FAILED', record_type='User', record_id=user.id,
                      new_values={'email': form.email.data}, user_id=user.id, description='Login failed - wrong password')
            flash('Invalid email or password.', 'danger')
            return render_template('auth/login.html', form=form)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        login_user(user, remember=form.remember_me.data)
        log_login(user.id, success=True)
        flash('Welcome back.', 'success')
        next_url = request.args.get('next') or url_for('dashboard.index')
        return redirect(next_url)
    return render_template('auth/login.html', form=form, allow_register=_allow_registration())


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def register():
    """First-time setup: create the initial admin account. Disabled once any user exists."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if not _allow_registration():
        flash('Registration is disabled. Contact an administrator for an account.', 'info')
        return redirect(url_for('auth.login'))
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if db.session.query(User).filter_by(email=email).first():
            flash('An account with that email already exists.', 'danger')
            return render_template('auth/register.html', form=form)
        user = User(
            email=email,
            is_superuser=True,
            is_active=True,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        # Assign ADMIN role if it exists (e.g. after seed_data); else superuser is enough
        admin_role = db.session.query(Role).filter_by(code='ADMIN').first()
        if admin_role:
            db.session.add(UserRole(user_id=user.id, role_id=admin_role.id))
        db.session.commit()
        flash('Account created. You can now sign in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = db.session.query(User).filter_by(email=form.email.data.strip().lower()).first()
        if user:
            # TODO: generate token, send email via notification_service
            flash('If that email exists, we sent a reset link.', 'info')
        else:
            flash('If that email exists, we sent a reset link.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html', form=form)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # TODO: verify token and load user
    form = ResetPasswordForm()
    if form.validate_on_submit():
        # TODO: set password, invalidate token
        flash('Password updated. You can log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', form=form, token=token)
