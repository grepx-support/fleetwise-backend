from backend.extensions import db

class CustomerServicePricing(db.Model):
    __tablename__ = 'customer_service_pricing'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Customer ID (cust_id)
    cust_id = db.Column(db.Integer, db.ForeignKey('customer.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Service ID (service_id) 
    service_id = db.Column(db.Integer, db.ForeignKey('service.id', ondelete='CASCADE'), nullable=False, index=True)
    
    vehicle_type_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle_type.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    price = db.Column(db.Float, nullable=True)
    
    # Unique constraint to prevent duplicate entries
    __table_args__ = (
        db.UniqueConstraint(
            "cust_id", "service_id", "vehicle_type_id",
            name="uq_csp_cust_service_vehicle",
        ),
    )