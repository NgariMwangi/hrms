"""Checkbox + hidden-field parsing for employee benefit forms."""
from flask import Flask

from app.routes.employees import _benefit_form_bool


def test_benefit_form_bool_checked_with_hidden_zero():
    app = Flask(__name__)
    with app.test_request_context(
        method='POST',
        data={'is_taxable': ['0', '1'], 'is_pensionable': ['0', '1']},
    ):
        assert _benefit_form_bool('is_taxable') is True
        assert _benefit_form_bool('is_pensionable') is True


def test_benefit_form_bool_unchecked_hidden_only():
    app = Flask(__name__)
    with app.test_request_context(method='POST', data={'is_taxable': '0', 'is_pensionable': '0'}):
        assert _benefit_form_bool('is_taxable') is False
        assert _benefit_form_bool('is_pensionable') is False


def test_benefit_form_bool_missing_uses_default():
    app = Flask(__name__)
    with app.test_request_context(method='POST', data={}):
        assert _benefit_form_bool('is_taxable', default=True) is True
        assert _benefit_form_bool('is_taxable', default=False) is False
