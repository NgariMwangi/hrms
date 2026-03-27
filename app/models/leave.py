"""
Leave types, balances, requests and public holidays.
"""
from decimal import Decimal
from app.extensions import db
from app.models.base import BaseModel


class LeaveType(BaseModel):
    """Leave type with rules: annual, sick, maternity, etc."""
    __tablename__ = 'leave_types'
    __table_args__ = (db.Index('ix_leave_types_code', 'code'),)

    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    days_per_year = db.Column(db.Numeric(6, 2), nullable=True)  # null = unlimited or manual
    accrues_monthly = db.Column(db.Boolean, default=False, nullable=False)
    days_per_month = db.Column(db.Numeric(5, 2), nullable=True)
    requires_approval = db.Column(db.Boolean, default=True, nullable=False)
    requires_document = db.Column(db.Boolean, default=False, nullable=False)  # e.g. sick note
    # How start/end dates are counted for days_requested: 'working' (Mon–Fri) vs 'calendar' (e.g. 90-day maternity)
    days_count_basis = db.Column(db.String(20), nullable=False, default='working')
    is_paid = db.Column(db.Boolean, default=True, nullable=False)
    min_days_request = db.Column(db.Numeric(4, 2), default=Decimal('0.5'), nullable=True)  # half-day
    max_consecutive_days = db.Column(db.Integer, nullable=True)
    carry_forward_max = db.Column(db.Integer, default=0, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class LeaveBalance(BaseModel):
    """Current leave balance per employee per leave type (updated by accrual and approvals)."""
    __tablename__ = 'leave_balances'
    __table_args__ = (
        db.UniqueConstraint('employee_id', 'leave_type_id', 'year', name='uq_leave_balance_emp_type_year'),
        db.Index('ix_leave_balances_employee_id', 'employee_id'),
        db.Index('ix_leave_balances_leave_type_id', 'leave_type_id'),
    )

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id', ondelete='CASCADE'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    opening_balance = db.Column(db.Numeric(8, 2), default=Decimal('0'), nullable=False)
    accrued = db.Column(db.Numeric(8, 2), default=Decimal('0'), nullable=False)
    used = db.Column(db.Numeric(8, 2), default=Decimal('0'), nullable=False)
    adjusted = db.Column(db.Numeric(8, 2), default=Decimal('0'), nullable=False)  # manual adjustment
    closing_balance = db.Column(db.Numeric(8, 2), nullable=False)  # opening + accrued + adjusted - used

    employee = db.relationship('Employee', backref='leave_balances')
    leave_type = db.relationship('LeaveType', backref='balances')


class LeaveRequest(BaseModel):
    """Leave request with workflow: pending, approved, rejected."""
    __tablename__ = 'leave_requests'
    __table_args__ = (
        db.Index('ix_leave_requests_employee_id', 'employee_id'),
        db.Index('ix_leave_requests_leave_type_id', 'leave_type_id'),
        db.Index('ix_leave_requests_status', 'status'),
        db.Index('ix_leave_requests_start_date', 'start_date'),
    )

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id', ondelete='CASCADE'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    days_requested = db.Column(db.Numeric(5, 2), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default='pending', nullable=False)  # pending, approved, rejected, cancelled
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    document_path = db.Column(db.String(500), nullable=True)  # if leave type requires document

    employee = db.relationship('Employee', backref='leave_requests')
    leave_type = db.relationship('LeaveType', backref='requests')


class PublicHoliday(BaseModel):
    """Kenyan public holidays - used to block leave and exclude from working days."""
    __tablename__ = 'public_holidays'
    __table_args__ = (db.Index('ix_public_holidays_date', 'date'),)

    date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    year = db.Column(db.Integer, nullable=False)
