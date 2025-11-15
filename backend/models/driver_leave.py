from backend.extensions import db
from sqlalchemy import false
from datetime import datetime

class DriverLeave(db.Model):
    __tablename__ = 'driver_leave'

    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=False)
    leave_type = db.Column(db.String(32), nullable=False)  # sick_leave, vacation, personal, emergency
    start_date = db.Column(db.String(32), nullable=False)  # Format: YYYY-MM-DD
    end_date = db.Column(db.String(32), nullable=False)    # Format: YYYY-MM-DD
    status = db.Column(db.String(32), default='approved', nullable=False)  # approved, pending, rejected, cancelled
    reason = db.Column(db.String(512), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())

    # Relationships
    driver = db.relationship('Driver', backref='leaves', lazy=True)
    created_by_user = db.relationship('User', foreign_keys=[created_by], lazy=True)

    @classmethod
    def query_active(cls):
        """Query active (non-deleted) records only"""
        return cls.query.filter_by(is_deleted=False)

    @classmethod
    def query_all(cls):
        """Query all records including deleted ones"""
        return cls.query

    def __repr__(self):
        return f'<DriverLeave {self.id}: Driver {self.driver_id} from {self.start_date} to {self.end_date}>'
