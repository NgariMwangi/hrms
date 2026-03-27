"""
SQLAlchemy models for HRMS Kenya.
Import all models here so they are registered with Flask-Migrate.
"""
from app.models.user import User, Role, Permission, UserRole
from app.models.employee import Employee
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.statutory import (
    StatutoryRateType,
    StatutoryRate,
    PayeBracket,
    NssfTier,
)
from app.models.audit import AuditLog
from app.models.payroll import (
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
)
from app.models.leave import LeaveType, LeaveBalance, LeaveRequest, PublicHoliday
from app.models.attendance import AttendanceRecord
from app.models.document import EmployeeDocument, DocumentCategory
from app.models.notification import Notification
from app.models.report import SavedReport
from app.models.employer import Employer

__all__ = [
    'User',
    'Role',
    'Permission',
    'UserRole',
    'Employee',
    'Department',
    'JobTitle',
    'StatutoryRateType',
    'StatutoryRate',
    'PayeBracket',
    'NssfTier',
    'AuditLog',
    'PayrollRun',
    'PayrollItem',
    'PayrollStatutoryRemittance',
    'PayrollRunManualDeduction',
    'Deduction',
    'EmployeeDeduction',
    'EmployeeSalary',
    'EmployeeAllowance',
    'Allowance',
    'EarningsDeductionType',
    'LeaveType',
    'LeaveBalance',
    'LeaveRequest',
    'PublicHoliday',
    'AttendanceRecord',
    'EmployeeDocument',
    'DocumentCategory',
    'Notification',
    'SavedReport',
    'Employer',
]
