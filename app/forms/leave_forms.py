"""Leave request and approval forms."""
from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Optional, ValidationError, NumberRange
from datetime import date


class LeaveTypeForm(FlaskForm):
    """Admin: define leave categories (annual, sick, etc.)."""
    code = StringField('Code', validators=[DataRequired()], render_kw={'placeholder': 'e.g. ANNUAL'})
    name = StringField('Name', validators=[DataRequired()])
    days_count_basis = SelectField(
        'Count leave length as',
        choices=[
            ('working', 'Working days (Mon–Fri, excludes weekends)'),
            ('calendar', 'Calendar days (includes weekends — e.g. 90-day maternity)'),
        ],
        validators=[DataRequired()],
    )
    days_per_year = DecimalField('Days per year', places=2, validators=[Optional()])
    accrues_monthly = BooleanField('Accrues monthly', default=False)
    days_per_month = DecimalField('Days accrued per month', places=2, validators=[Optional()])
    requires_approval = BooleanField('Requires approval', default=True)
    requires_document = BooleanField('Requires document upload', default=False)
    is_paid = BooleanField('Paid leave', default=True)
    min_days_request = DecimalField('Minimum days per request', places=2, validators=[Optional(), NumberRange(min=0)])
    max_consecutive_days = IntegerField('Max consecutive days (blank = no limit)', validators=[Optional()])
    carry_forward_max = IntegerField('Max days carry forward to next year', validators=[Optional()])
    is_active = BooleanField('Active', default=True)
    submit = SubmitField('Save')


class LeaveRequestForm(FlaskForm):
    """Employee leave request."""
    leave_type_id = SelectField('Leave Type', coerce=int, validators=[DataRequired()])
    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=[DataRequired()])
    reason = TextAreaField('Reason', validators=[Optional()])
    submit = SubmitField('Submit Request')

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError('End date must be after start date.')


class LeaveApprovalForm(FlaskForm):
    """Manager approval/rejection."""
    action = SelectField('Action', choices=[('approve', 'Approve'), ('reject', 'Reject')], validators=[DataRequired()])
    review_notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Submit')
