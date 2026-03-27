"""
Seed database with initial roles, permissions, statutory rates (Kenya 2026), reference data.

Values below are aligned with the current development database export so a fresh production
run produces the same reference data. Run after migrations:

  python -c "from scripts.seed_data import run; run()"

Or: flask shell, then: from scripts.seed_data import run; run()
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

# Load .env from project root so DATABASE_URL is set (even when run from another dir)
_project_root = Path(__file__).resolve().parent.parent
_env = _project_root / ".env"
if _env.exists():
    from dotenv import load_dotenv
    load_dotenv(_env)

from app import create_app
from app.extensions import db
from app.models.user import Role, Permission, RolePermission
from app.models.statutory import StatutoryRate, PayeBracket, NssfTier
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.leave import LeaveType
from app.models.document import DocumentCategory
from app.models.payroll import Allowance


def run():
    app = create_app()
    with app.app_context():
        # Permissions (fixed catalogue)
        perms = [
            ('view_employees', 'View employees'),
            ('create_employees', 'Create employees'),
            ('edit_employees', 'Edit employees'),
            ('view_departments', 'View departments'),
            ('manage_departments', 'Manage departments'),
            ('view_payroll', 'View payroll'),
            ('process_payroll', 'Process payroll'),
            ('approve_payroll', 'Approve payroll'),
            ('view_leave', 'View leave'),
            ('manage_leave_types', 'Manage leave types'),
            ('approve_leave', 'Approve leave'),
            ('view_attendance', 'View attendance'),
            ('view_reports', 'View reports'),
            ('manage_statutory', 'Manage statutory rates'),
            ('manage_settings', 'Manage settings'),
            ('view_audit_log', 'View audit log'),
        ]
        for code, name in perms:
            if db.session.query(Permission).filter_by(code=code).first() is None:
                db.session.add(Permission(code=code, name=name))
        db.session.commit()

        # Role → permission codes (must match production DB role_permissions)
        role_perms = {
            'ADMIN': [
                'approve_leave', 'approve_payroll', 'create_employees', 'edit_employees',
                'manage_departments', 'manage_settings', 'manage_statutory', 'process_payroll',
                'view_attendance', 'view_audit_log', 'view_departments', 'view_employees',
                'view_leave', 'view_payroll', 'view_reports',
            ],
            'HR_MANAGER': [
                'approve_leave', 'approve_payroll', 'create_employees', 'edit_employees',
                'manage_departments', 'manage_statutory', 'process_payroll', 'view_attendance',
                'view_audit_log', 'view_departments', 'view_employees', 'view_leave',
                'view_payroll', 'view_reports',
            ],
            'HR_STAFF': [
                'approve_leave', 'create_employees', 'edit_employees', 'process_payroll',
                'view_attendance', 'view_departments', 'view_employees', 'view_leave',
                'view_payroll', 'view_reports',
            ],
            'MANAGER': [
                'approve_leave', 'view_departments', 'view_employees', 'view_leave', 'view_reports',
            ],
            'EMPLOYEE': ['view_leave'],
        }
        for code, name in [
            ('ADMIN', 'Administrator'),
            ('HR_MANAGER', 'HR Manager'),
            ('HR_STAFF', 'HR Staff'),
            ('MANAGER', 'Manager'),
            ('EMPLOYEE', 'Employee'),
        ]:
            role = db.session.query(Role).filter_by(code=code).first()
            if role is None:
                role = Role(code=code, name=name)
                db.session.add(role)
                db.session.flush()
            for pcode in role_perms.get(code, []):
                perm = db.session.query(Permission).filter_by(code=pcode).first()
                if perm and not db.session.query(RolePermission).filter_by(
                    role_id=role.id, permission_id=perm.id
                ).first():
                    db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        db.session.commit()

        # Statutory rates (effective from 2026-01-01)
        eff_from = date(2026, 1, 1)
        for code, value, desc in [
            ('SHIF_PERCENT', 2.75, 'SHIF 2.75% of gross'),
            ('HOUSING_LEVY_PERCENT', 1.5, 'Housing Levy 1.5% employee'),
            ('PERSONAL_RELIEF', 2400, 'Monthly personal relief (KES)'),
        ]:
            if db.session.query(StatutoryRate).filter(
                StatutoryRate.code == code, StatutoryRate.effective_from == eff_from
            ).first() is None:
                db.session.add(
                    StatutoryRate(code=code, effective_from=eff_from, value=value, description=desc)
                )
        db.session.commit()

        # PAYE brackets (aligned with current DB / Finance Act bands)
        if db.session.query(PayeBracket).filter(PayeBracket.effective_from == eff_from).first() is None:
            for order, min_a, max_a, rate in [
                (1, 0, 24000, 10),
                (2, 24001, 32333, 25),
                (3, 32334, 500000, 30),
                (4, 500001, 800000, 32.5),
                (5, 800001, None, 35),
            ]:
                db.session.add(
                    PayeBracket(
                        effective_from=eff_from,
                        bracket_order=order,
                        min_amount=min_a,
                        max_amount=max_a,
                        rate_percent=rate,
                    )
                )
        db.session.commit()

        # NSSF tiers (Feb 2026)
        nssf_from = date(2026, 2, 1)
        if db.session.query(NssfTier).filter(NssfTier.effective_from == nssf_from).first() is None:
            db.session.add(
                NssfTier(
                    effective_from=nssf_from,
                    tier_number=1,
                    pensionable_min=0,
                    pensionable_max=9000,
                    employee_percent=6,
                    employer_percent=6,
                    employee_max_amount=540,
                    employer_max_amount=540,
                )
            )
            db.session.add(
                NssfTier(
                    effective_from=nssf_from,
                    tier_number=2,
                    pensionable_min=9001,
                    pensionable_max=108000,
                    employee_percent=6,
                    employer_percent=6,
                    employee_max_amount=5940,
                    employer_max_amount=5940,
                )
            )
        db.session.commit()

        # Leave types (aligned with current DB)
        leave_specs = [
            # code, name, days_per_year, accrues_monthly, days_per_month, is_paid, days_count_basis
            ('ANNUAL', 'Annual Leave', Decimal('21'), True, Decimal('1.75'), True, 'working'),
            ('SICK', 'Sick Leave', Decimal('14'), False, None, True, 'working'),
            ('MATERNITY', 'Maternity Leave', Decimal('90'), False, None, True, 'calendar'),
            ('PATERNITY', 'Paternity Leave', Decimal('14'), False, None, True, 'calendar'),
            ('COMPASSIONATE', 'Compassionate Leave', Decimal('5'), False, None, True, 'working'),
            ('UNPAID', 'Unpaid Leave', Decimal('0'), False, None, False, 'working'),
        ]
        for code, name, days_py, accrues, dpm, is_paid, basis in leave_specs:
            if db.session.query(LeaveType).filter_by(code=code).first() is None:
                db.session.add(
                    LeaveType(
                        code=code,
                        name=name,
                        days_per_year=days_py,
                        accrues_monthly=accrues,
                        days_per_month=dpm,
                        requires_approval=True,
                        requires_document=False,
                        days_count_basis=basis,
                        is_paid=is_paid,
                        min_days_request=Decimal('0.5'),
                        carry_forward_max=0,
                        is_active=True,
                    )
                )
        db.session.commit()

        # Departments (reference rows from current DB)
        for code, name in [
            ('FIN', 'FINANCE'),
            ('GEN', 'General'),
            ('IT', 'IT'),
        ]:
            if db.session.query(Department).filter_by(code=code).first() is None:
                db.session.add(Department(code=code, name=name))
        db.session.commit()

        # Job titles
        for code, name in [
            ('STAFF', 'Staff'),
            ('SWE', 'Software Engineer'),
        ]:
            if db.session.query(JobTitle).filter_by(code=code).first() is None:
                db.session.add(JobTitle(code=code, name=name))
        db.session.commit()

        # Allowances (company-wide types — matches current DB codes/names/flags)
        for code, name, is_taxable, is_pensionable in [
            ('*', 'House Allowance', True, True),
            ('HOUSE', 'House Allowance', True, True),
            ('MEAL', 'Meal Allowance', True, False),
            ('MEDICAL', 'Medical Allowance', True, False),
            ('OTHER', 'Other Allowance', True, False),
            ('P', 'Transport Allowance', True, True),
            ('TRANSPORT', 'Transport Allowance', True, False),
        ]:
            if db.session.query(Allowance).filter_by(code=code).first() is None:
                db.session.add(
                    Allowance(
                        code=code,
                        name=name,
                        is_taxable=is_taxable,
                        is_pensionable=is_pensionable,
                    )
                )
        db.session.commit()

        # Document categories for employee documents
        for code, name, track_expiry in [
            ('CONTRACT', 'Contract', True),
            ('ID', 'National ID', True),
            ('KRA_PIN', 'KRA PIN', False),
            ('NSSF', 'NSSF', False),
            ('CERTIFICATE', 'Certificate', True),
            ('OTHER', 'Other', False),
        ]:
            if db.session.query(DocumentCategory).filter_by(code=code).first() is None:
                db.session.add(DocumentCategory(code=code, name=name, track_expiry=track_expiry))
        db.session.commit()

        print(
            'Seed completed: permissions, roles, statutory rates, PAYE/NSSF, leave types, '
            'departments, job titles, allowances, document categories.'
        )
