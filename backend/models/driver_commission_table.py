from backend.extensions import db

class DriverCommissionTable(db.Model):
    __tablename__ = 'driver_commission_table'
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False)
    job_type = db.Column(db.String(64), nullable=False)
    vehicle_type = db.Column(db.String(64), nullable=False)
    commission_amount = db.Column(db.Float, nullable=False)
    __table_args__ = (db.UniqueConstraint('driver_id', 'job_type', 'vehicle_type', name='_driver_commission_uc'),) 