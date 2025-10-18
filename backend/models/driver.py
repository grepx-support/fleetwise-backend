from backend.extensions import db
from sqlalchemy import false
from backend.models.driver_remark import DriverRemark

class Driver(db.Model):
    __tablename__ = 'driver'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(128), nullable=True)
    mobile = db.Column(db.String(32), nullable=True)
    license_number = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), default='Active', nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())
    # jobs = db.relationship('Job', backref='driver_rel', lazy=True, overlaps="driver_rel") 

    remarks = db.relationship("DriverRemark", back_populates="driver", cascade="all, delete-orphan")
    
    @classmethod
    def query_active(cls):
        """Query active (non-deleted) records only"""
        return cls.query.filter_by(is_deleted=False)
    
    @classmethod
    def query_all(cls):
        """Query all records including deleted ones"""
        return cls.query