"""Payroll run and configuration forms."""
from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, SubmitField, TextAreaField, StringField
from wtforms.validators import DataRequired, Optional, NumberRange, Length


class PayrollRunForm(FlaskForm):
    """Create new payroll run."""
    pay_month = SelectField('Month', coerce=int, choices=[
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
    ], validators=[DataRequired()])
    pay_year = IntegerField('Year', validators=[DataRequired(), NumberRange(min=2020, max=2030)])
    country_code = StringField('Country (ISO2)', validators=[DataRequired(), Length(min=2, max=2)], default='KE')
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Create Payroll Run')


class PayrollApproveForm(FlaskForm):
    """Approve payroll run."""
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Approve Payroll')
