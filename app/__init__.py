"""
HRMS Kenya - Application Factory.
Monolithic Flask app with blueprints for Kenyan statutory-compliant HR.
"""
import os
import logging
from pathlib import Path

from flask import Flask
from dotenv import load_dotenv
from sqlalchemy.exc import ProgrammingError

from app.extensions import (
    db,
    migrate,
    login_manager,
    csrf,
    limiter,
    mail,
)
from config import get_config


load_dotenv()


def _ensure_writable_dir(path_value: str, fallback_name: str) -> tuple[Path, bool]:
    """
    Ensure directory exists and is writable.
    Returns (resolved_path, used_fallback).
    """
    target = Path(path_value)
    try:
        target.mkdir(parents=True, exist_ok=True)
        return target, False
    except PermissionError:
        fallback = Path('/tmp/hrms') / fallback_name
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback, True


def create_app(config_object=None):
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static',
        instance_relative_config=True,
    )

    # Load config
    config = config_object or get_config()
    app.config.from_object(config)

    # Ensure instance and storage dirs exist; fallback to /tmp/hrms/* when container FS is read-only.
    instance_dir, instance_fallback = _ensure_writable_dir(app.instance_path, 'instance')
    if instance_fallback:
        app.instance_path = str(instance_dir)

    upload_dir, upload_fallback = _ensure_writable_dir(app.config['UPLOAD_FOLDER'], 'uploads')
    if upload_fallback:
        app.config['UPLOAD_FOLDER'] = str(upload_dir)

    if not app.config.get('TESTING'):
        log_dir, log_fallback = _ensure_writable_dir(app.config['LOG_DIR'], 'logs')
        if log_fallback:
            app.config['LOG_DIR'] = str(log_dir)

    # Initialize extensions
    _init_extensions(app)

    # Load all models and create tables *before* blueprints (so metadata has full dependency order).
    with app.app_context():
        from app.models import (  # noqa: F401
            User,
            Role,
            Permission,
            UserRole,
            Employee,
            Department,
            JobTitle,
            StatutoryRateType,
            StatutoryRate,
            PayeBracket,
            NssfTier,
            AuditLog,
            PayrollRun,
            PayrollItem,
            PayrollStatutoryRemittance,
            PayrollRunManualDeduction,
            EmployeeSalary,
            EmployeeAllowance,
            Allowance,
            Deduction,
            EmployeeDeduction,
            EarningsDeductionType,
            LeaveType,
            LeaveBalance,
            LeaveRequest,
            PublicHoliday,
            AttendanceRecord,
            EmployeeDocument,
            DocumentCategory,
            Notification,
            SavedReport,
            Employer,
        )
        _create_tables_safe(app)

    # Register blueprints (after tables so route imports don't affect metadata)
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Context processors
    _register_context_processors(app)

    # Configure logging
    _configure_logging(app)

    # Root URL rule
    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('dashboard.index'))

    return app


# Explicit creation order: dependencies first. SQLAlchemy's sorted_tables can be wrong.
_TABLE_ORDER = (
    'permissions', 'roles', 'role_permissions',
    'departments', 'job_titles', 'document_categories',
    'earnings_deduction_types', 'allowances', 'leave_types', 'public_holidays',
    'statutory_rate_types', 'statutory_rates', 'paye_brackets', 'nssf_tiers',
    'employees',   # before users (User.employee_id -> employees)
    'employers',
    'users', 'user_roles',
    'audit_logs', 'leave_balances', 'leave_requests', 'employee_salaries', 'employee_allowances',
    'deductions', 'employee_deductions',
    'attendance_records', 'employee_documents',
    'payroll_runs', 'payroll_run_manual_deductions', 'payroll_items', 'payroll_statutory_remitances',
    'notifications', 'saved_reports',
)


def _create_tables_safe(app):
    """Create all tables in explicit dependency order. Ignore already exists; retry on dependency missing."""
    meta = db.metadata
    order_index = {name: i for i, name in enumerate(_TABLE_ORDER)}
    # Sort all tables: known names by our order, then any others last
    tables = sorted(
        list(meta.tables.values()),
        key=lambda t: order_index.get(t.name, len(_TABLE_ORDER)),
    )
    for _ in range(20):
        deferred = 0
        for table in tables:
            try:
                table.create(db.engine, checkfirst=True)
            except ProgrammingError as e:
                msg = str(e).lower()
                if "already exists" in msg or "duplicate" in msg:
                    continue
                if "does not exist" in msg or "undefined table" in msg:
                    deferred += 1
                    continue
                raise
        if deferred == 0:
            break
    # Ensure users table exists (often missed due to order/FK); create employees then users if needed
    for name in ('employees', 'users'):
        if name in meta.tables:
            try:
                meta.tables[name].create(db.engine, checkfirst=True)
            except ProgrammingError as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    pass
                else:
                    app.logger.warning("Could not create table %s: %s", name, e)

def _init_extensions(app):
    """Initialize Flask extensions with app."""
    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(app.root_path), 'migrations'))

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    login_manager.session_protection = 'strong'

    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    # User loader for Flask-Login
    from app.models.user import User
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))


def _register_blueprints(app):
    """Register application blueprints."""
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.employees import employees_bp
    from app.routes.departments import departments_bp
    from app.routes.leave import leave_bp
    from app.routes.attendance import attendance_bp
    from app.routes.payroll import payroll_bp
    from app.routes.statutory import statutory_bp
    from app.routes.reports import reports_bp
    from app.routes.settings import settings_bp
    from app.routes.api import api_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(employees_bp, url_prefix='/employees')
    app.register_blueprint(departments_bp, url_prefix='/departments')
    try:
        from app.routes.job_titles import job_titles_bp
        app.register_blueprint(job_titles_bp, url_prefix='/job-titles')
    except Exception as e:
        app.logger.warning('Job titles blueprint not registered: %s', e)
    try:
        from app.routes.allowances import allowances_bp
        app.register_blueprint(allowances_bp, url_prefix='/allowances')
    except Exception as e:
        app.logger.warning('Allowances blueprint not registered: %s', e)
    app.register_blueprint(leave_bp, url_prefix='/leave')
    app.register_blueprint(attendance_bp, url_prefix='/attendance')
    app.register_blueprint(payroll_bp, url_prefix='/payroll')
    app.register_blueprint(statutory_bp, url_prefix='/statutory')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp, url_prefix='/api')


def _register_error_handlers(app):
    """Register custom error handlers."""
    from flask import render_template

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500


def _register_context_processors(app):
    """Register template context processors."""
    from app.context_processors import inject_config, inject_permissions, register_template_filters
    app.context_processor(inject_permissions)
    app.context_processor(inject_config)
    register_template_filters(app)


def _configure_logging(app):
    """Configure application logging."""
    if app.config.get('TESTING'):
        app.logger.setLevel(logging.DEBUG)
        return

    app.logger.setLevel(getattr(logging, app.config.get('LOG_LEVEL', 'INFO')))
    if not app.config.get('LOG_TO_STDOUT'):
        log_dir = app.config['LOG_DIR']
        file_handler = logging.FileHandler(
            os.path.join(log_dir, 'hrms.log'),
            encoding='utf-8',
        )
        file_handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
        ))
        app.logger.addHandler(file_handler)
