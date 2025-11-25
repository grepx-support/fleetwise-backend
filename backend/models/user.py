from datetime import datetime, timedelta
from backend.extensions import db
from flask_security import UserMixin
from .role import roles_users

class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean(), default=True)
    fs_uniquifier = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=True)  # New name field
    # Optionally link to Customer/Driver
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)
    roles = db.relationship('Role', secondary=roles_users, backref=db.backref('users', lazy='dynamic'))
    # Flask-Security-Too trackable fields
    last_login_at = db.Column(db.DateTime())
    current_login_at = db.Column(db.DateTime())
    last_login_ip = db.Column(db.String(100))
    current_login_ip = db.Column(db.String(100))
    login_count = db.Column(db.Integer)
    android_device_token = db.Column(db.String(1024),nullable=True)
    ios_device_token = db.Column(db.String(1024),nullable=True)
    # Account lockout fields for security
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime(), nullable=True)
    last_failed_login = db.Column(db.DateTime(), nullable=True)
    driver = db.relationship('Driver', backref='user', uselist=False)
    customer = db.relationship('Customer', backref='user', uselist=False)

    def is_account_locked(self):
        """Check if account is currently locked (read-only check)"""
        if self.locked_until:
            return datetime.utcnow() < self.locked_until
        return False

    def unlock_if_expired(self):
        """Unlock account if lock period has expired. Returns True if unlocked."""
        if self.locked_until and datetime.utcnow() >= self.locked_until:
            self.locked_until = None
            self.failed_login_attempts = 0
            return True
        return False

    def record_failed_login(self, max_attempts=5, lockout_duration_minutes=10):
        """
        Record a failed login attempt and lock account if threshold exceeded

        Args:
            max_attempts: Maximum failed attempts before lockout (default: 5)
            lockout_duration_minutes: Duration to lock account in minutes (default: 10)
        """
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        self.last_failed_login = datetime.utcnow()

        if self.failed_login_attempts >= max_attempts:
            self.locked_until = datetime.utcnow() + timedelta(minutes=lockout_duration_minutes)

    def reset_failed_login_attempts(self):
        """Reset failed login attempts on successful login"""
        self.failed_login_attempts = 0
        self.last_failed_login = None
        self.locked_until = None