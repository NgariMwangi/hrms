"""System and statutory settings forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, DateField, SubmitField, SelectField, IntegerField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Optional, NumberRange, Email


class StatutoryRateForm(FlaskForm):
    """Add/edit statutory rate (e.g. SHIF %, Housing Levy %)."""
    code = StringField('Code', validators=[DataRequired()])
    effective_from = DateField('Effective From', validators=[DataRequired()])
    effective_to = DateField('Effective To', validators=[Optional()])
    value = FloatField('Value (%) or Amount', validators=[InputRequired()])
    description = StringField('Description', validators=[Optional()])
    submit = SubmitField('Save')


class PayeBracketForm(FlaskForm):
    """PAYE tax bracket."""
    effective_from = DateField('Effective From', validators=[DataRequired()])
    effective_to = DateField('Effective To', validators=[Optional()])
    bracket_order = IntegerField('Order', validators=[InputRequired(), NumberRange(min=1, max=50)])
    min_amount = FloatField('Min Taxable (KES)', validators=[InputRequired()])
    max_amount = FloatField('Max Taxable (KES)', validators=[Optional()])
    rate_percent = FloatField('Rate (%)', validators=[InputRequired()])
    submit = SubmitField('Save')


class EmployerForm(FlaskForm):
    """Company/employer details shown on reports and exported documents."""
    name = StringField('Employer name', validators=[DataRequired()])
    kra_pin = StringField('Employer KRA PIN', validators=[Optional()])

    email = StringField('Employer email', validators=[Optional(), Email()])
    phone = StringField('Employer phone', validators=[Optional()])

    physical_address = TextAreaField('Physical address', validators=[Optional()])
    postal_address = StringField('Postal address', validators=[Optional()])

    registration_number = StringField('Registration number', validators=[Optional()])

    submit = SubmitField('Save')
