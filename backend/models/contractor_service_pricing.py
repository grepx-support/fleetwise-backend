from backend.extensions import db

class ContractorServicePricing(db.Model):
    __tablename__ = 'contractor_service_pricing'
    id = db.Column(db.Integer, primary_key=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey('contractor.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=False)
    cost = db.Column(db.Float, nullable=False, default=0.0)
    
    # Ensure unique constraint for contractor_id and service_id combination
    __table_args__ = (db.UniqueConstraint('contractor_id', 'service_id', name='unique_contractor_service'),)
    
    # Relationships
    service = db.relationship('Service', backref='contractor_pricing', lazy=True)