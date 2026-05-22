"""
Validators for employee identifiers and contact details.
Kenya-specific formats are not enforced — IDs may be alphanumeric (e.g. Uganda NIN).
"""
import re

# Letters, digits, and common separators used on national/statutory IDs
IDENTIFIER_PATTERN = re.compile(r'^[\w\s\-/.]+$', re.UNICODE)


def validate_optional_identifier(
    value: str,
    *,
    field_name: str = 'Value',
    max_length: int = 50,
) -> tuple[bool, str]:
    """
    Optional ID / reference number: allow mixed letters and digits.
    Returns (is_valid, error_message).
    """
    if not value or not value.strip():
        return True, ''
    value = value.strip()
    if len(value) > max_length:
        return False, f'{field_name} must be at most {max_length} characters.'
    if not IDENTIFIER_PATTERN.match(value):
        return False, (
            f'{field_name} may only contain letters, numbers, spaces, and - / . _'
        )
    return True, ''


def validate_kra_pin(value: str) -> tuple[bool, str]:
    """Tax ID / PIN (Kenya KRA or equivalent) — alphanumeric, not digits-only."""
    return validate_optional_identifier(value, field_name='Tax PIN', max_length=20)


def validate_national_id(value: str) -> tuple[bool, str]:
    """National ID / NIN — alphanumeric (e.g. Uganda, Kenya, other countries)."""
    return validate_optional_identifier(value, field_name='National ID', max_length=30)


def validate_nssf_number(value: str) -> tuple[bool, str]:
    """Social security / pension reference number."""
    return validate_optional_identifier(value, field_name='NSSF number', max_length=30)


def validate_nhif_shif_number(value: str) -> tuple[bool, str]:
    """Health insurance / SHIF reference number."""
    return validate_optional_identifier(value, field_name='NHIF/SHIF number', max_length=30)


def normalize_phone_ke(value: str) -> str:
    """Normalize Kenyan phone to +254XXXXXXXXX."""
    if not value or not value.strip():
        return ''
    value = re.sub(r'\s+', '', value.strip())
    if value.startswith('+254'):
        return '+254' + value[4:].lstrip('0') if len(value) > 4 else value
    if value.startswith('254'):
        return '+' + value
    if value.startswith('0'):
        return '+254' + value[1:]
    if value.startswith('7') and len(value) == 9:
        return '+254' + value
    if value.startswith('1') and len(value) == 9:  # landline
        return '+254' + value
    return value


def validate_phone_ke(value: str) -> tuple[bool, str]:
    """Validate Kenyan phone: 07XX, 01XX, +254."""
    if not value or not value.strip():
        return True, ''
    normalized = normalize_phone_ke(value)
    if len(normalized) < 12:
        return False, 'Invalid Kenyan phone number.'
    if not normalized.startswith('+254'):
        return False, 'Use format: 07XX XXX XXX or +254 7XX XXX XXX.'
    return True, ''
