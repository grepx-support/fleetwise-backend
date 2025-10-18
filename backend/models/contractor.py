from backend.extensions import db
from sqlalchemy import false

class Contractor(db.Model):
    __tablename__ = 'contractor'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    contact_person = db.Column(db.String(128), nullable=True)
    contact_number = db.Column(db.String(32), nullable=True)
    email = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(32), default='Active', nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())
    
    # Relationships
    service_pricing = db.relationship('ContractorServicePricing', backref='contractor', lazy=True, cascade='all, delete-orphan')
    jobs = db.relationship('Job', back_populates='contractor', lazy=True)
    
    @classmethod
    def query_active(cls):
        """Query active (non-deleted) records only"""
        return cls.query.filter_by(is_deleted=False)
    
    @classmethod
    def query_all(cls):
        """Query all records including deleted ones"""
        return cls.query