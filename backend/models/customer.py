from backend.extensions import db

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
    sub_customers = db.relationship('SubCustomer', backref='customer', lazy=True, cascade='all, delete-orphan')
    invoices = db.relationship('Invoice', backref='customer_invoice', lazy=True, cascade='all, delete-orphan')