from backend.extensions import db
from sqlalchemy import false

class Vehicle(db.Model):
    __tablename__ = 'vehicle'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    number = db.Column(db.String(64), nullable=False)
    type = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(32), default='Active', nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())
    drivers = db.relationship('Driver', backref='vehicle', lazy=True)
    # jobs = db.relationship('Job', backref='vehicle_rel', lazy=True, overlaps="vehicle_rel")
    
    @classmethod
    def query_active(cls):
        """Query active (non-deleted) records only"""
        return cls.query.filter_by(is_deleted=False)
    
    @classmethod
    def query_all(cls):
        """Query all records including deleted ones"""
        return cls.query