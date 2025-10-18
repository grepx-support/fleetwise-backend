from backend.extensions import db
from sqlalchemy import false

class VehicleType(db.Model):
    __tablename__ = 'vehicle_type'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    description = db.Column(db.String(256), nullable=True)
    status = db.Column(db.Boolean, default=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())
    create = db.Column(db.DateTime, default=db.func.current_timestamp())
    update = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())
    
    @classmethod
    def query_active(cls):
        """Query active (non-deleted) records only"""
        return cls.query.filter_by(is_deleted=False)
    
    @classmethod
    def query_all(cls):
        """Query all records including deleted ones"""
        return cls.query