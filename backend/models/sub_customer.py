from backend.extensions import db

class SubCustomer(db.Model):
    __tablename__ = 'sub_customer'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=True, index=True)
    __table_args__ = (db.UniqueConstraint('name', 'customer_id', name='_subcustomer_uc'),) 