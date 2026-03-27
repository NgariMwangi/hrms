"""
Kenyan-specific validators: KRA PIN, National ID, NSSF, NHIF/SHIF, phone.
"""
import re


# KRA PIN: A followed by 9 alphanumeric (e.g. A001234567P)
KRA_PIN_PATTERN = re.compile(r'^[A-Z]\d{8}[A-Z]$', re.IGNORECASE)


def validate_kra_pin(value: str) -> tuple[bool, str]:
    """
    Validate KRA PIN format. A + 9 alphanumeric.
    Returns (is_valid, error_message).
    """
    if not value or not value.strip():
        return True, ''  # optional field
    value = value.strip().upper()
    if len(value) != 10:
        return False, 'KRA PIN must be 10 characters (e.g. A001234567P).'
    if not KRA_PIN_PATTERN.match(value):
        return False, 'KRA PIN must start with a letter, followed by 8 digits and end with a letter.'
    return True, ''


def validate_national_id(value: str) -> tuple[bool, str]:
    """Kenyan National ID: 7-8 digits (old) or 8 digits (new generation)."""
    if not value or not value.strip():
        return True, ''
    value = value.strip()
    if not value.isdigit():
        return False, 'National ID must contain only digits.'
    if len(value) not in (7, 8):
        return False, 'National ID must be 7 or 8 digits.'
    return True, ''


def validate_nssf_number(value: str) -> tuple[bool, str]:
    """NSSF number: typically 7-9 digits."""
    if not value or not value.strip():
        return True, ''
    value = value.strip()
    if not value.isdigit():
        return False, 'NSSF number must contain only digits.'
    if len(value) < 7 or len(value) > 9:
        return False, 'NSSF number must be 7 to 9 digits.'
    return True, ''


def validate_nhif_shif_number(value: str) -> tuple[bool, str]:
    """NHIF/SHIF number: typically 9 digits."""
    if not value or not value.strip():
        return True, ''
    value = value.strip()
    if not value.isdigit():
        return False, 'NHIF/SHIF number must contain only digits.'
    if len(value) != 9:
        return False, 'NHIF/SHIF number must be 9 digits.'
    return True, ''


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
