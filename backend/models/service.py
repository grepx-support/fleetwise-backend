from backend.extensions import db
from sqlalchemy import Numeric, false

class Service(db.Model):
    __tablename__ = 'service'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(32), default='Active', nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())

    # Ancillary charge fields
    is_ancillary = db.Column(db.Boolean, default=False, nullable=False, server_default=false())
    condition_type = db.Column(db.String(64))  # 'time_range', 'additional_stops', 'always', None
    condition_config = db.Column(db.Text)  # JSON string for condition configuration
    is_per_occurrence = db.Column(db.Boolean, default=False, nullable=False, server_default=false())  # For additional stops: charge per extra stop
    
    # jobs = db.relationship('Job', backref='service_rel', lazy=True, overlaps="service_rel")
    
    # Relationship with ServicesVehicleTypePrice model
    # This relationship is defined in ServicesVehicleTypePrice model with cascade delete
    
    @classmethod
    def query_active(cls):
        """Query active (non-deleted) records only"""
        return cls.query.filter_by(is_deleted=False)
    
    @classmethod
    def query_all(cls):
        """Query all records including deleted ones"""
        return cls.query