"""
Employee master data - full lifecycle and Kenyan-specific identifiers.
"""
from decimal import Decimal
from app.extensions import db
from app.models.base import BaseModel


class Employee(BaseModel):
    """Employee record: personal info, Kenyan IDs, employment details, bank."""
    __tablename__ = 'employees'

    # Auto-generated
    employee_number = db.Column(db.String(30), unique=True, nullable=False)

    # Personal
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(20), nullable=True)  # Male, Female, Other
    marital_status = db.Column(db.String(30), nullable=True)
    nationality = db.Column(db.String(100), nullable=True)

    # Kenyan identifiers
    national_id = db.Column(db.String(30), nullable=True)
    passport_number = db.Column(db.String(50), nullable=True)
    kra_pin = db.Column(db.String(20), nullable=True)
    nssf_number = db.Column(db.String(30), nullable=True)
    nhif_number = db.Column(db.String(30), nullable=True)  # legacy / SHIF number

    # Contact
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    phone_alt = db.Column(db.String(30), nullable=True)
    address = db.Column(db.Text, nullable=True)
    postal_address = db.Column(db.String(255), nullable=True)
    emergency_contact_name = db.Column(db.String(200), nullable=True)
    emergency_contact_phone = db.Column(db.String(30), nullable=True)

    # Employment
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True)
    job_title_id = db.Column(db.Integer, db.ForeignKey('job_titles.id', ondelete='SET NULL'), nullable=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(30), default='active', nullable=False)  # active, terminated, resigned, retired, on_leave, suspended
    employment_type = db.Column(db.String(30), nullable=True)  # permanent, contract, probation, intern, casual
    hire_date = db.Column(db.Date, nullable=False)
    probation_end_date = db.Column(db.Date, nullable=True)
    confirmation_date = db.Column(db.Date, nullable=True)
    contract_end_date = db.Column(db.Date, nullable=True)
    termination_date = db.Column(db.Date, nullable=True)
    termination_reason = db.Column(db.String(500), nullable=True)
    photo_url = db.Column(db.String(500), nullable=True)

    # Bank (for payroll)
    bank_name = db.Column(db.String(100), nullable=True)
    bank_branch = db.Column(db.String(100), nullable=True)
    bank_account_number = db.Column(db.String(50), nullable=True)
    bank_code = db.Column(db.String(20), nullable=True)
    swift_code = db.Column(db.String(20), nullable=True)

    department = db.relationship('Department', backref='employees')
    job_title = db.relationship('JobTitle', backref='employees')
    manager = db.relationship('Employee', remote_side='Employee.id', backref='direct_reports')

    @property
    def full_name(self):
        parts = [self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.last_name)
        return ' '.join(parts)

    def __str__(self):
        return f"{self.employee_number} - {self.full_name}"
