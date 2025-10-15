import pytest
from backend.server import app
from backend.extensions import db
from backend.models.user import User
from backend.models.driver import Driver
from backend.models.job import Job
from flask import url_for
from flask_security.utils import hash_password


def setup_module(module):
    # Initialize in-memory DB
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    module.app_ctx = app.app_context()
    module.app_ctx.push()
    db.create_all()


def teardown_module(module):
    db.session.remove()
    db.drop_all()
    module.app_ctx.pop()


def create_driver_and_user():
    driver = Driver(name='Test Driver', mobile='12345678')
    db.session.add(driver)
    db.session.commit()

    user = User(
        email='driver@example.com',
        password=hash_password('password'),
        fs_uniquifier='uniq',
        driver_id=driver.id
    )
    db.session.add(user)
    db.session.commit()
    return driver, user


def test_driver_can_update_collection(monkeypatch):
    driver, user = create_driver_and_user()

    # Create job assigned to driver
    job = Job(
        customer_id=1,
        service_type='standard',
        pickup_location='A',
        dropoff_location='B',
        pickup_date='2025-10-10',
        base_price=10.0,
        final_price=12.0,
        driver_id=driver.id
    )
    db.session.add(job)
    db.session.commit()

    # Mock current_user to our user for auth_required
    class DummyCurrentUser:
        def __init__(self, user):
            self.id = user.id
            self.driver_id = user.driver_id
        def has_role(self, role):
            return False

    monkeypatch.setattr('backend.api.mobileapi.driver.current_user', DummyCurrentUser(user))

    # Bypass auth decorator by invoking the view function directly inside a request context
    from backend.api.mobileapi import driver as driver_module

    with app.test_request_context(f'/api/mobile/driver/jobs/{job.id}/update-collection', method='PUT', json={'cash_to_collect': 15.5}):
        # Ensure current_user is our dummy user inside the module
        monkeypatch.setattr('backend.api.mobileapi.driver.current_user', DummyCurrentUser(user))
        # Call the original unwrapped view function to bypass auth decorator
        unwrapped = getattr(driver_module.update_job_collection, '__wrapped__', None)
        assert unwrapped is not None, 'Expected view to be wrapped by decorator with __wrapped__'
        resp = unwrapped(job.id)

    # The view returns a Flask response tuple or Response; normalize
    if isinstance(resp, tuple):
        response_obj, status = resp
    else:
        response_obj = resp
        status = getattr(resp, 'status_code', 200)

    assert status == 200
    data = response_obj.get_json() if hasattr(response_obj, 'get_json') else response_obj
    assert float(data['cash_to_collect']) == 15.5

    # Verify DB updated
    updated = Job.query.get(job.id)
    assert updated.cash_to_collect == 15.5
