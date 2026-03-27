"""Template context processors: permissions, config."""
from flask import session
from flask_login import current_user


def register_template_filters(app):
    """Jinja filters used across templates."""

    @app.template_filter('fmt_days')
    def fmt_days(value):
        """Show day counts without unnecessary decimals (21 not 21.00; 0.5 stays 0.5)."""
        if value is None:
            return ''
        try:
            f = float(value)
        except (TypeError, ValueError):
            return value
        if f != f:  # NaN
            return value
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
        return '%g' % f


def inject_permissions():
    """Expose current_user and has_permission to templates."""
    def has_permission(code):
        if not current_user.is_authenticated:
            return False
        return current_user.has_permission(code)
    return {
        'current_user': current_user,
        'has_permission': has_permission,
    }


def inject_config():
    """Expose app config values needed in templates."""
    from flask import current_app
    return {
        'app_name': 'HRMS Kenya',
        'currency': current_app.config.get('DEFAULT_CURRENCY', 'KES'),
    }
