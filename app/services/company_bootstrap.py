"""
Default reference data for a new tenant (leave types, document categories, Kenya statutory for a country).
Called after creating a Company so the org can be used immediately.
"""
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.document import DocumentCategory
from app.models.leave import LeaveType
from app.models.statutory import StatutoryRate, PayeBracket, NssfTier


def bootstrap_company_defaults(company_id: int, country_code: str = 'KE') -> None:
    """Idempotent: only inserts rows missing for this company (+ country for statutory)."""
    cc = (country_code or 'KE').upper()[:2]

    leave_specs = [
        ('ANNUAL', 'Annual Leave', Decimal('24'), True, Decimal('2'), True, 'working'),
        ('SICK', 'Sick Leave', Decimal('14'), False, None, True, 'working'),
        ('MATERNITY', 'Maternity Leave', Decimal('90'), False, None, True, 'calendar'),
        ('PATERNITY', 'Paternity Leave', Decimal('14'), False, None, True, 'calendar'),
        ('COMPASSIONATE', 'Compassionate Leave', Decimal('5'), False, None, True, 'working'),
        ('UNPAID', 'Unpaid Leave', Decimal('0'), False, None, False, 'working'),
    ]
    for code, name, days_py, accrues, dpm, is_paid, basis in leave_specs:
        if (
            db.session.query(LeaveType)
            .filter(LeaveType.company_id == company_id, LeaveType.code == code)
            .first()
        ):
            continue
        db.session.add(
            LeaveType(
                company_id=company_id,
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
                carry_forward_max=10,
                is_active=True,
            )
        )

    for code, name, track_expiry in [
        ('CONTRACT', 'Contract', True),
        ('ID', 'National ID', True),
        ('KRA_PIN', 'KRA PIN', False),
        ('NSSF', 'NSSF', False),
        ('CERTIFICATE', 'Certificate', True),
        ('OTHER', 'Other', False),
    ]:
        if (
            db.session.query(DocumentCategory)
            .filter(DocumentCategory.company_id == company_id, DocumentCategory.code == code)
            .first()
        ):
            continue
        db.session.add(
            DocumentCategory(company_id=company_id, code=code, name=name, track_expiry=track_expiry)
        )

    if cc == 'KE':
        eff_from = date(2026, 1, 1)
        if not (
            db.session.query(StatutoryRate)
            .filter(
                StatutoryRate.company_id == company_id,
                StatutoryRate.country_code == cc,
                StatutoryRate.code == 'SHIF_PERCENT',
                StatutoryRate.effective_from == eff_from,
            )
            .first()
        ):
            for code, value, desc in [
                ('SHIF_PERCENT', 2.75, 'SHIF 2.75% of gross'),
                ('HOUSING_LEVY_PERCENT', 1.5, 'Housing Levy 1.5% employee'),
                ('PERSONAL_RELIEF', 2400, 'Monthly personal relief (KES)'),
            ]:
                db.session.add(
                    StatutoryRate(
                        company_id=company_id,
                        country_code=cc,
                        code=code,
                        effective_from=eff_from,
                        value=value,
                        description=desc,
                    )
                )

        if not (
            db.session.query(PayeBracket)
            .filter(
                PayeBracket.company_id == company_id,
                PayeBracket.country_code == cc,
                PayeBracket.effective_from == eff_from,
            )
            .first()
        ):
            for order, min_a, max_a, rate in [
                (1, 0, 24000, 10),
                (2, 24001, 32333, 25),
                (3, 32334, 500000, 30),
                (4, 500001, 800000, 32.5),
                (5, 800001, None, 35),
            ]:
                db.session.add(
                    PayeBracket(
                        company_id=company_id,
                        country_code=cc,
                        effective_from=eff_from,
                        bracket_order=order,
                        min_amount=min_a,
                        max_amount=max_a,
                        rate_percent=rate,
                    )
                )

        # NSSF tier bands: use an early effective_from so draft payroll for past months
        # still picks up tiers (strict as_at filtering is in statutory_service with fallback).
        nssf_from = date(2024, 1, 1)
        if not (
            db.session.query(NssfTier)
            .filter(
                NssfTier.company_id == company_id,
                NssfTier.country_code == cc,
                NssfTier.effective_from == nssf_from,
            )
            .first()
        ):
            db.session.add(
                NssfTier(
                    company_id=company_id,
                    country_code=cc,
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
                    company_id=company_id,
                    country_code=cc,
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
