from backend.extensions import db

class Vehicle(db.Model):
    __tablename__ = 'vehicle'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    number = db.Column(db.String(64), nullable=False)
    type = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(32), default='Active', nullable=False)
    drivers = db.relationship('Driver', backref='vehicle', lazy=True)
    # jobs = db.relationship('Job', backref='vehicle_rel', lazy=True, overlaps="vehicle_rel") 