"""Tests for statutory_service (PAYE, NSSF, SHIF, Housing)."""
from datetime import date
from decimal import Decimal
import pytest
from app import create_app
from app.extensions import db
from app.models.statutory import StatutoryRate, PayeBracket, NssfTier
from app.services.statutory_service import (
    get_personal_relief,
    get_shif_percent,
    get_housing_levy_percent,
    calculate_nssf,
    calculate_paye,
    calculate_shif,
    calculate_housing_levy,
)
from config import TestingConfig


@pytest.fixture
def app():
    app = create_app(TestingConfig)
    return app


@pytest.fixture
def app_ctx(app):
    with app.app_context():
        yield


@pytest.fixture
def seed_statutory(app_ctx):
    """Seed minimal statutory data for tests."""
    db.create_all()
    eff = date(2026, 1, 1)
    for code, value in [('PERSONAL_RELIEF', 2400), ('SHIF_PERCENT', 2.75), ('HOUSING_LEVY_PERCENT', 1.5)]:
        if db.session.query(StatutoryRate).filter_by(code=code, effective_from=eff).first() is None:
            db.session.add(StatutoryRate(code=code, effective_from=eff, value=value))
    for order, min_a, max_a, rate in [(1, 0, 30000, 10), (2, 30001, 50000, 25), (3, 50001, None, 35)]:
        if db.session.query(PayeBracket).filter_by(effective_from=eff, bracket_order=order).first() is None:
            db.session.add(PayeBracket(effective_from=eff, bracket_order=order, min_amount=min_a, max_amount=max_a, rate_percent=rate))
    nssf_from = date(2026, 2, 1)
    if db.session.query(NssfTier).filter_by(effective_from=nssf_from).first() is None:
        db.session.add(NssfTier(effective_from=nssf_from, tier_number=1, pensionable_min=0, pensionable_max=9000,
                                employee_percent=6, employer_percent=6, employee_max_amount=540, employer_max_amount=540))
        db.session.add(NssfTier(effective_from=nssf_from, tier_number=2, pensionable_min=9001, pensionable_max=108000,
                                employee_percent=6, employer_percent=6, employee_max_amount=5940, employer_max_amount=5940))
    db.session.commit()


def test_get_personal_relief(app_ctx, seed_statutory):
    assert get_personal_relief(date(2026, 6, 1)) == Decimal('2400')


def test_get_shif_percent(app_ctx, seed_statutory):
    assert get_shif_percent(date(2026, 6, 1)) == Decimal('2.75')


def test_calculate_shif(app_ctx, seed_statutory):
    # 2.75% of 100000
    assert calculate_shif(Decimal('100000'), date(2026, 6, 1)) == Decimal('2750.00')


def test_calculate_housing_levy(app_ctx, seed_statutory):
    # 1.5% of 100000
    assert calculate_housing_levy(Decimal('100000'), date(2026, 6, 1)) == Decimal('1500.00')


def test_calculate_paye(app_ctx, seed_statutory):
    # 50,000 taxable: 30k @ 10% + 20k @ 25% = 3000 + 5000 = 8000, minus relief 2400 = 5600
    tax = calculate_paye(Decimal('50000'), date(2026, 6, 1))
    assert tax == Decimal('5600')


def test_calculate_nssf(app_ctx, seed_statutory):
    # Pensionable 20,000: Tier I 0-9000 -> 6% of 9000 = 540 each; Tier II 9001-20000 -> 6% of 10999 = 659.94 each
    emp, empr = calculate_nssf(Decimal('20000'), date(2026, 3, 1))
    assert emp == Decimal('1199.94')
    assert empr == Decimal('1199.94')
