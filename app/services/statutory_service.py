"""
Kenyan statutory deduction calculations (2026).
Uses rates from database with effective dates - no code change when legislation changes.
PAYE, NSSF (Tier I/II), SHIF, Housing Levy.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.extensions import db
from app.models.statutory import StatutoryRate, PayeBracket, NssfTier

# Currency amounts: always round to 2 decimal places (KES cents).
TWO_DP = Decimal('0.01')


def _get_rate(code: str, as_at: date) -> Decimal:
    """Get single rate value for code valid on as_at."""
    r = (
        db.session.query(StatutoryRate)
        .filter(
            StatutoryRate.code == code,
            StatutoryRate.effective_from <= as_at,
            (StatutoryRate.effective_to.is_(None)) | (StatutoryRate.effective_to >= as_at),
        )
        .order_by(StatutoryRate.effective_from.desc())
        .first()
    )
    if not r:
        return Decimal('0')
    return Decimal(str(r.value)).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def get_personal_relief(as_at: date) -> Decimal:
    """Personal relief amount (monthly) for PAYE."""
    return _get_rate('PERSONAL_RELIEF', as_at)


def get_shif_percent(as_at: date) -> Decimal:
    """SHIF rate: 2.75% of gross (2026)."""
    return _get_rate('SHIF_PERCENT', as_at)


def get_housing_levy_percent(as_at: date) -> Decimal:
    """Housing levy: 1.5% of gross, employee only."""
    return _get_rate('HOUSING_LEVY_PERCENT', as_at)


def calculate_nssf(pensionable_pay: Decimal, as_at: date) -> tuple:
    """
    NSSF Feb 2026: Tier I first 9,000 (6%+6%), Tier II 9,001-108,000 (6%+6% capped).
    Returns (employee_contribution, employer_contribution).
    """
    tiers = (
        db.session.query(NssfTier)
        .filter(
            NssfTier.effective_from <= as_at,
            (NssfTier.effective_to.is_(None)) | (NssfTier.effective_to >= as_at),
        )
        .order_by(NssfTier.tier_number)
        .all()
    )
    if not tiers:
        return Decimal('0'), Decimal('0')

    emp_total = Decimal('0')
    empr_total = Decimal('0')
    # Use contiguous tier boundaries to avoid off-by-one effects from stored min values (e.g. 9001).
    prev_high = Decimal('0')
    for tier in tiers:
        high = Decimal(str(tier.pensionable_max))
        if pensionable_pay <= prev_high:
            continue
        taxable_in_tier = min(pensionable_pay, high) - prev_high
        emp_pct = Decimal(str(tier.employee_percent)) / 100
        empr_pct = Decimal(str(tier.employer_percent)) / 100
        emp_contrib = taxable_in_tier * emp_pct
        empr_contrib = taxable_in_tier * empr_pct
        if tier.employee_max_amount is not None:
            emp_contrib = min(emp_contrib, Decimal(str(tier.employee_max_amount)))
        if tier.employer_max_amount is not None:
            empr_contrib = min(empr_contrib, Decimal(str(tier.employer_max_amount)))
        emp_total += emp_contrib
        empr_total += empr_contrib
        prev_high = high
    return emp_total, empr_total


def calculate_nssf_with_breakdown(pensionable_pay: Decimal, as_at: date) -> tuple:
    """
    NSSF with tier-level breakdown.
    Returns (employee_total, employer_total, breakdown)
    where breakdown is list of dicts: [{tier_number, employee, employer}, ...]
    """
    tiers = (
        db.session.query(NssfTier)
        .filter(
            NssfTier.effective_from <= as_at,
            (NssfTier.effective_to.is_(None)) | (NssfTier.effective_to >= as_at),
        )
        .order_by(NssfTier.tier_number)
        .all()
    )
    if not tiers:
        return Decimal('0'), Decimal('0'), []

    emp_total = Decimal('0')
    empr_total = Decimal('0')
    breakdown = []
    prev_high = Decimal('0')
    for tier in tiers:
        high = Decimal(str(tier.pensionable_max))
        if pensionable_pay <= prev_high:
            continue
        taxable_in_tier = min(pensionable_pay, high) - prev_high
        emp_pct = Decimal(str(tier.employee_percent)) / 100
        empr_pct = Decimal(str(tier.employer_percent)) / 100
        emp_contrib = taxable_in_tier * emp_pct
        empr_contrib = taxable_in_tier * empr_pct
        if tier.employee_max_amount is not None:
            emp_contrib = min(emp_contrib, Decimal(str(tier.employee_max_amount)))
        if tier.employer_max_amount is not None:
            empr_contrib = min(empr_contrib, Decimal(str(tier.employer_max_amount)))
        emp_contrib = emp_contrib.quantize(Decimal('0.01'))
        empr_contrib = empr_contrib.quantize(Decimal('0.01'))
        emp_total += emp_contrib
        empr_total += empr_contrib
        breakdown.append(
            {
                'tier_number': int(tier.tier_number),
                'employee': emp_contrib,
                'employer': empr_contrib,
            }
        )
        prev_high = high
    return emp_total, empr_total, breakdown


def calculate_paye_breakdown(taxable_pay: Decimal, as_at: date) -> dict:
    """
    PAYE components from brackets and personal relief (monthly chargeable income).

    Returns:
        tax_before_relief: tax on chargeable income before personal relief
        personal_relief_applied: portion of relief that offsets tax (<= monthly relief cap)
        paye: PAYE after relief (same rules as calculate_paye)
    """
    brackets = (
        db.session.query(PayeBracket)
        .filter(
            PayeBracket.effective_from <= as_at,
            (PayeBracket.effective_to.is_(None)) | (PayeBracket.effective_to >= as_at),
        )
        .order_by(PayeBracket.bracket_order)
        .all()
    )
    z = Decimal('0').quantize(TWO_DP, rounding=ROUND_HALF_UP)
    if not brackets:
        return {'tax_before_relief': z, 'personal_relief_applied': z, 'paye': z}

    taxable_pay = Decimal(str(taxable_pay)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    tax = Decimal('0')
    prev_ceiling = Decimal('0')
    for br in brackets:
        high = Decimal(str(br.max_amount)) if br.max_amount is not None else Decimal('999999999')
        rate = Decimal(str(br.rate_percent)) / 100
        if taxable_pay <= prev_ceiling:
            break
        band_income = min(taxable_pay, high) - prev_ceiling
        if band_income > 0:
            tier_tax = (band_income * rate).quantize(TWO_DP, rounding=ROUND_HALF_UP)
            tax += tier_tax
        prev_ceiling = high

    relief = get_personal_relief(as_at)
    tax = tax.quantize(TWO_DP, rounding=ROUND_HALF_UP)
    paye = (tax - relief).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    if paye < 0:
        paye = Decimal('0').quantize(TWO_DP, rounding=ROUND_HALF_UP)
    relief_applied = (tax - paye).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    return {
        'tax_before_relief': tax,
        'personal_relief_applied': relief_applied,
        'paye': paye,
    }


def calculate_paye(taxable_pay: Decimal, as_at: date) -> Decimal:
    """
    PAYE from tax brackets (monthly taxable pay).
    Uses cumulative band ceilings so income in each band is min(taxable, high) - prev_ceiling,
    then rounds tax before relief and final PAYE to 2 decimal places.
    """
    return calculate_paye_breakdown(taxable_pay, as_at)['paye']


def calculate_shif(gross_pay: Decimal, as_at: date) -> Decimal:
    """SHIF: 2.75% of gross, no cap."""
    pct = get_shif_percent(as_at)
    return (gross_pay * pct / 100).quantize(Decimal('0.01'))


def calculate_housing_levy(gross_pay: Decimal, as_at: date) -> Decimal:
    """Housing levy: 1.5% of gross, employee only."""
    pct = get_housing_levy_percent(as_at)
    return (gross_pay * pct / 100).quantize(Decimal('0.01'))


def get_pensionable_pay(basic_salary: Decimal, house_allowance: Decimal, other_pensionable: Decimal = None) -> Decimal:
    """Pensionable pay for NSSF = basic + house allowance (typically)."""
    other = other_pensionable or Decimal('0')
    return (basic_salary + house_allowance + other).quantize(Decimal('0.01'))
