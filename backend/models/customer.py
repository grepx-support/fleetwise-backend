from backend.extensions import db
from sqlalchemy import false

class Customer(db.Model):
    __tablename__ = 'customer'
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(128), nullable=True, index=True)
    mobile = db.Column(db.String(32), nullable=True)
    company_name = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(32), default='Active', nullable=False)
    address = db.Column(db.String(256), nullable=True)
    city = db.Column(db.String(128), nullable=True)
    state = db.Column(db.String(128), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)
    country = db.Column(db.String(128), nullable=True)
    type = db.Column(db.String(64), nullable=True)  # e.g., Individual / Business / Corporate
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())
    sub_customers = db.relationship('SubCustomer', backref='customer', lazy=True, cascade='all, delete-orphan')
    invoices = db.relationship('Invoice', backref='customer_invoice', lazy=True, cascade='all, delete-orphan')
    
    @classmethod
    def query_active(cls):
        """Query active (non-deleted) records only"""
        return cls.query.filter_by(is_deleted=False)
    
    @classmethod
    def query_all(cls):
        """Query all records including deleted ones"""
        return cls.query