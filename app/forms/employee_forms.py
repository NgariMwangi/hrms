"""Employee create/edit forms with Kenyan validators."""
from flask_wtf import FlaskForm
from wtforms import (
    StringField, DateField, SelectField, TextAreaField, SubmitField,
    FloatField, IntegerField,
)
from wtforms.validators import DataRequired, Optional, Email, ValidationError
from datetime import date


def _coerce_optional_int(value):
    """Coerce for optional SelectField: '' -> None, else int(value)."""
    if value is None or value == '':
        return None
    return int(value)


def _validate_kra_pin(form, field):
    if field.data:
        from app.utils.validators import validate_kra_pin
        ok, msg = validate_kra_pin(field.data)
        if not ok:
            raise ValidationError(msg)


def _validate_national_id(form, field):
    if field.data:
        from app.utils.validators import validate_national_id
        ok, msg = validate_national_id(field.data)
        if not ok:
            raise ValidationError(msg)


def _validate_phone(form, field):
    if field.data:
        from app.utils.validators import validate_phone_ke
        ok, msg = validate_phone_ke(field.data)
        if not ok:
            raise ValidationError(msg)


class EmployeeForm(FlaskForm):
    """Create/Edit employee."""
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    middle_name = StringField('Middle Name', validators=[Optional()])
    date_of_birth = DateField('Date of Birth', validators=[Optional()])
    gender = SelectField('Gender', choices=[('', '--'), ('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')], validators=[Optional()])
    marital_status = SelectField('Marital Status', choices=[
        ('', '--'), ('Single', 'Single'), ('Married', 'Married'), ('Divorced', 'Divorced'), ('Widowed', 'Widowed')
    ], validators=[Optional()])
    nationality = StringField('Nationality', validators=[Optional()])
    national_id = StringField('National ID', validators=[Optional(), _validate_national_id])
    passport_number = StringField('Passport Number', validators=[Optional()])
    kra_pin = StringField('KRA PIN', validators=[Optional()])
    nssf_number = StringField('NSSF Number', validators=[Optional()])
    nhif_number = StringField('NHIF/SHIF Number', validators=[Optional()])
    email = StringField('Email', validators=[Optional(), Email()])
    phone = StringField('Phone', validators=[Optional(), _validate_phone])
    phone_alt = StringField('Alternate Phone', validators=[Optional(), _validate_phone])
    address = TextAreaField('Address', validators=[Optional()])
    postal_address = StringField('Postal Address', validators=[Optional()])
    emergency_contact_name = StringField('Emergency Contact Name', validators=[Optional()])
    emergency_contact_phone = StringField('Emergency Contact Phone', validators=[Optional(), _validate_phone])
    department_id = SelectField('Department', coerce=_coerce_optional_int, validators=[Optional()])
    job_title_id = SelectField('Job Title', coerce=_coerce_optional_int, validators=[Optional()])
    manager_id = SelectField('Manager', coerce=_coerce_optional_int, validators=[Optional()])
    status = SelectField('Status', choices=[
        ('active', 'Active'), ('terminated', 'Terminated'), ('resigned', 'Resigned'),
        ('retired', 'Retired'), ('on_leave', 'On Leave'), ('suspended', 'Suspended'),
    ], default='active')
    employment_type = SelectField('Employment Type', choices=[
        ('', '--'), ('permanent', 'Permanent'), ('contract', 'Contract'),
        ('probation', 'Probation'), ('intern', 'Intern'), ('casual', 'Casual'),
    ], validators=[Optional()])
    hire_date = DateField('Hire Date', validators=[DataRequired()])
    probation_end_date = DateField('Probation End Date', validators=[Optional()])
    confirmation_date = DateField('Confirmation Date', validators=[Optional()])
    contract_end_date = DateField('Contract End Date', validators=[Optional()])
    bank_name = StringField('Bank Name', validators=[Optional()])
    bank_branch = StringField('Branch', validators=[Optional()])
    bank_account_number = StringField('Account Number', validators=[Optional()])
    bank_code = StringField('Bank Code', validators=[Optional()])
    swift_code = StringField('SWIFT Code', validators=[Optional()])
    submit = SubmitField('Save')

    def validate_hire_date(self, field):
        if field.data and field.data > date.today():
            raise ValidationError('Hire date cannot be in the future.')

    def validate_date_of_birth(self, field):
        if field.data:
            from datetime import timedelta
            if field.data > date.today() - timedelta(days=365 * 18):
                raise ValidationError('Employee must be at least 18 years old.')


class EmployeeSalaryForm(FlaskForm):
    """Employee basic salary record. Allowances are added separately via Allowance table."""
    basic_salary = FloatField('Basic Salary (KES)', validators=[DataRequired()])
    pension_employee_percent = FloatField('Pension Employee %', default=0, validators=[Optional()])
    pension_employer_percent = FloatField('Pension Employer %', default=0, validators=[Optional()])
    effective_from = DateField('Effective From', validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save')
