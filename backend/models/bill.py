from backend.extensions import db
from datetime import datetime
from sqlalchemy.sql import func
from sqlalchemy import Numeric
from decimal import Decimal

class Bill(db.Model):
    __tablename__ = 'bill'
    id = db.Column(db.Integer, primary_key=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey('contractor.id', ondelete='CASCADE'), nullable=True, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id', ondelete='CASCADE'), nullable=True, index=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    # Status field: 'Generated' for new/unpaid bills, other values for paid/processed bills
    status = db.Column(db.String(16), nullable=False, default='Generated', index=True)
    total_amount = db.Column(Numeric(precision=12, scale=2), nullable=True)
    file_path = db.Column(db.String(255), nullable=True)
    
    # Relationships
    contractor = db.relationship('Contractor', backref='bills', lazy='select')
    
    # Relationship to Job - this creates the backref so job.bill works
    jobs = db.relationship(
        'Job',
        backref='bill',
        lazy='select'
    )


    def __repr__(self):
        return f"<Bill {self.id} - {self.status}>"
    
    @property
    def driver(self):
        """
        Get driver from explicit driver_id or from associated jobs.
        For driver bills: contractor_id is None and driver comes from jobs.
        For contractor bills: driver_id may be None and we use contractor info instead.
        """
        # If driver_id is explicitly set, use that
        if self.driver_id:
            from backend.models.driver import Driver
            return Driver.query.get(self.driver_id)
        
        # For driver bills, get driver from associated jobs
        if self.contractor_id is None and self.jobs:
            return self.jobs[0].driver if self.jobs[0].driver else None
        
        return None


# Commenting out BillItem class since you don't want to use it
# class BillItem(db.Model):
#     __tablename__ = 'bill_item'
#     id = db.Column(db.Integer, primary_key=True)
#     bill_id = db.Column(db.Integer, db.ForeignKey('bill.id', ondelete='CASCADE'), nullable=False)
#     job_id = db.Column(db.Integer, db.ForeignKey('job.id', ondelete='CASCADE'), nullable=False)
#     amount = db.Column(db.Numeric(precision=12, scale=2), nullable=False)
#     
#     # Relationships
#     bill = db.relationship('Bill', backref=db.backref('bill_items', lazy=True, cascade='all, delete-orphan'))
#     job = db.relationship('Job', backref='bill_items', lazy=True)