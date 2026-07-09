"""Employee login email stays aligned with employee work email."""
from datetime import date

import pytest

from app import create_app
from app.extensions import db
from app.models.company import Branch, Company
from app.models.employee import Employee
from app.models.user import User
from app.services.employee_account_service import (
    sync_employee_email_from_user,
    sync_user_email_from_employee,
)
from config import TestingConfig


@pytest.fixture
def app():
    return create_app(TestingConfig)


@pytest.fixture
def app_ctx(app):
    with app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture
def linked_employee_user(app_ctx):
    company = Company(name='Sync Co', is_active=True)
    db.session.add(company)
    db.session.flush()
    branch = Branch(company_id=company.id, name='HQ', country_code='KE')
    db.session.add(branch)
    db.session.flush()
    employee = Employee(
        company_id=company.id,
        branch_id=branch.id,
        first_name='Jane',
        last_name='Doe',
        email='old.work@example.com',
        hire_date=date(2024, 1, 1),
    )
    db.session.add(employee)
    db.session.flush()
    user = User(
        email='old.login@example.com',
        company_id=company.id,
        employee_id=employee.id,
        is_active=True,
    )
    user.set_password('password123')
    db.session.add(user)
    db.session.commit()
    return employee, user


def test_sync_user_email_from_employee_updates_login(linked_employee_user):
    employee, user = linked_employee_user
    employee.email = 'new.work@example.com'

    assert sync_user_email_from_employee(employee) is None
    assert user.email == 'new.work@example.com'


def test_sync_employee_email_from_user_updates_employee_record(linked_employee_user):
    employee, user = linked_employee_user
    user.email = 'new.login@example.com'

    sync_employee_email_from_user(user)
    assert employee.email == 'new.login@example.com'


def test_sync_user_email_from_employee_rejects_duplicate(linked_employee_user):
    employee, user = linked_employee_user
    other = User(email='taken@example.com', company_id=employee.company_id, is_active=True)
    other.set_password('password123')
    db.session.add(other)
    db.session.commit()

    employee.email = 'taken@example.com'
    assert sync_user_email_from_employee(employee) is not None
