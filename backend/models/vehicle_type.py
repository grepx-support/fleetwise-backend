from backend.extensions import db

class VehicleType(db.Model):
    __tablename__ = 'vehicle_type'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    description = db.Column(db.String(256), nullable=True)
    status = db.Column(db.Boolean, default=True)
    create = db.Column(db.DateTime, default=db.func.current_timestamp())
    update = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())