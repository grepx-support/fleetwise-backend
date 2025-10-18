from backend.extensions import db

class ServicesVehicleTypePrice(db.Model):
    __tablename__ = 'service_vehicle_type_price'

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id', ondelete='CASCADE'), nullable=False)
    vehicle_type_id = db.Column(db.Integer, db.ForeignKey('vehicle_type.id', ondelete='CASCADE'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    
    # Relationship with Service model
    service = db.relationship('Service', backref=db.backref('vehicle_prices', lazy='dynamic', cascade='all, delete-orphan'))
    
    # Relationship with VehicleType model
    # This relationship is defined in VehicleType model with cascade delete