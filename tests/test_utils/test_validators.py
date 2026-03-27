"""Tests for Kenyan validators."""
import pytest
from app.utils.validators import (
    validate_kra_pin,
    validate_national_id,
    validate_nhif_shif_number,
    validate_phone_ke,
    normalize_phone_ke,
)


def test_validate_kra_pin_valid():
    ok, msg = validate_kra_pin('A001234567P')
    assert ok is True
    assert msg == ''


def test_validate_kra_pin_invalid_length():
    ok, msg = validate_kra_pin('A00123456')
    assert ok is False
    assert '10 characters' in msg


def test_validate_national_id_valid():
    ok, msg = validate_national_id('12345678')
    assert ok is True


def test_validate_national_id_invalid():
    ok, msg = validate_national_id('12345')
    assert ok is False


def test_normalize_phone_ke():
    assert normalize_phone_ke('0712345678') == '+254712345678'
    assert normalize_phone_ke('254712345678') == '+254712345678'
