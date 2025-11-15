from backend.extensions import db
from sqlalchemy import false
from datetime import datetime

class JobReassignment(db.Model):
    __tablename__ = 'job_reassignment'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    driver_leave_id = db.Column(db.Integer, db.ForeignKey('driver_leave.id'), nullable=False)

    # Original assignment
    original_driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)
    original_vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    original_contractor_id = db.Column(db.Integer, db.ForeignKey('contractor.id'), nullable=True)

    # New assignment
    reassignment_type = db.Column(db.String(32), nullable=False)  # driver, vehicle, contractor
    new_driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'), nullable=True)
    new_vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)
    new_contractor_id = db.Column(db.Integer, db.ForeignKey('contractor.id'), nullable=True)

    # Metadata
    notes = db.Column(db.String(512), nullable=True)
    reassigned_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reassigned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())

    # Relationships
    job = db.relationship('Job', backref='reassignments', lazy=True)
    driver_leave = db.relationship('DriverLeave', backref='job_reassignments', lazy=True)
    original_driver = db.relationship('Driver', foreign_keys=[original_driver_id], lazy=True)
    new_driver = db.relationship('Driver', foreign_keys=[new_driver_id], lazy=True)
    reassigned_by_user = db.relationship('User', foreign_keys=[reassigned_by], lazy=True)

    @classmethod
    def query_active(cls):
        """Query active (non-deleted) records only"""
        return cls.query.filter_by(is_deleted=False)

    @classmethod
    def query_all(cls):
        """Query all records including deleted ones"""
        return cls.query

    def __repr__(self):
        return f'<JobReassignment {self.id}: Job {self.job_id} - Type: {self.reassignment_type}>'
