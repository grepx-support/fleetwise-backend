from backend.extensions import db
from backend.models.driver_commission_table import DriverCommissionTable
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
    commissions = db.relationship(DriverCommissionTable, backref='driver', lazy=True)
    # jobs = db.relationship('Job', backref='driver_rel', lazy=True, overlaps="driver_rel") 

    remarks = db.relationship("DriverRemark", back_populates="driver", cascade="all, delete-orphan")