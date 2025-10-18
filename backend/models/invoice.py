from backend.extensions import db
from datetime import datetime
from sqlalchemy.sql import func
from sqlalchemy import Numeric
from sqlalchemy.ext.hybrid import hybrid_property



class Invoice(db.Model):
    __tablename__ = 'invoice'
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False, index=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(16), nullable=False, default='Unpaid', index=True)
    # total_amount = db.Column(db.Float, nullable=True)
    total_amount = db.Column(db.Numeric(precision=12, scale=2), nullable=True)  # changed from Float to Numeric
    # jobs = db.relationship('Job', backref='invoice_rel', lazy=True, cascade='all, delete-orphan', overlaps="invoice_rel") 
    file_path = db.Column(db.String(255), nullable=True) 
    remaining_amount_invoice = db.Column(Numeric(precision=12, scale=2), nullable=True)

    
    # Relationship to payments
    payments = db.relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")

    @property
    def paid_amount(self):
        return sum(p.amount for p in self.payments)

    @property
    def remaining_amount(self):
        return self.total_amount - self.paid_amount
    # @hybrid_property
    # def remaining_amount(self):
    #     total_paid = sum(p.amount for p in self.payments) if self.payments else 0
    #     return float(self.total_amount or 0) - float(total_paid or 0)
    def update_remaining_amount(self):
        total_paid = sum(float(p.amount or 0) for p in self.payments)
        self.remaining_amount_invoice = float(self.total_amount or 0) - total_paid
    # def recalc_amounts(self):
    #     self.remaining_amount_invoice = self.remaining_amount
    #     self.update_status()
    # def recalc_amounts(self):
    #     total_paid = sum(p.amount for p in self.payments)
    #     self.remaining_amount_invoice = float(self.total_amount or 0) - float(total_paid or 0)
    
    #     if self.remaining_amount_invoice <= 0:
    #         self.status = "Paid"
    #     elif total_paid > 0:
    #         self.status = "Partially Paid"
    #     else:
    #         self.status = "Unpaid"
    def update_status(self):
        if self.remaining_amount <= 0:
            self.status = "Paid"
        elif self.paid_amount > 0:
            self.status = "Partially Paid"
        else:
            self.status = "Unpaid"


class Payment(db.Model):
    __tablename__ = 'payment'

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id', ondelete='CASCADE'), nullable=False, index=True)
    # amount = db.Column(db.Float, nullable=False)
    amount = db.Column(Numeric(precision=12, scale=2), nullable=False)  # Use Decimal
    # date = db.Column(db.DateTime, default=datetime.utcnow)
    date = db.Column(db.DateTime, server_default=func.now())
    reference_number = db.Column(db.String(50), nullable=True)  # e.g., UPI txn, bank ref
    notes = db.Column(db.String(255), nullable=True)
    receipt_path = db.Column(db.String(255), nullable=True)

    # Relationship back to invoice
    invoice = db.relationship("Invoice", back_populates="payments")    