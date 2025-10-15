from backend.extensions import db

class Contractor(db.Model):
    __tablename__ = 'contractor'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    contact_person = db.Column(db.String(128), nullable=True)
    contact_number = db.Column(db.String(32), nullable=True)
    email = db.Column(db.String(128), nullable=True)
    status = db.Column(db.String(32), default='Active', nullable=False)
    
    # Relationships
    service_pricing = db.relationship('ContractorServicePricing', backref='contractor', lazy=True, cascade='all, delete-orphan')
    jobs = db.relationship('Job', back_populates='contractor', lazy=True)