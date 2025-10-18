from backend.extensions import db
from sqlalchemy import Numeric

class Service(db.Model):
    __tablename__ = 'service'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(32), default='Active', nullable=False)
    # jobs = db.relationship('Job', backref='service_rel', lazy=True, overlaps="service_rel")
    
    # Relationship with ServicesVehicleTypePrice model
    # This relationship is defined in ServicesVehicleTypePrice model with cascade delete