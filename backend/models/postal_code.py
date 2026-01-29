from backend.extensions import db
from datetime import datetime, timezone

class PostalCode(db.Model):
    __tablename__ = 'postal_codes'
    
    id = db.Column(db.Integer, primary_key=True, index=True)
    postal_code = db.Column(db.String(10), nullable=False, index=True)
    address = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def to_dict(self):
        return {
            'id': self.id,
            'postal_code': self.postal_code,
            'address': self.address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<PostalCode {self.postal_code}: {self.address[:50]}...>'