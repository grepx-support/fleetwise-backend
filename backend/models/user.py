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
    driver = db.relationship('Driver', backref='user', uselist=False)