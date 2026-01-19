from backend.extensions import db
from sqlalchemy import false, Index
from datetime import datetime


class LeaveOverride(db.Model):
    """
    Time-window override within a driver leave period.
    Allows driver to be available for job assignment during specific hours
    while maintaining leave status for remaining hours.

    Constraints:
    - Override date must fall within leave's start_date to end_date
    - start_time < end_time (same day)
    - Can only be created on APPROVED leaves
    - No overlapping overrides on same leave for same date/time
    """
    __tablename__ = 'leave_override'

    id = db.Column(db.Integer, primary_key=True)
    driver_leave_id = db.Column(db.Integer, db.ForeignKey('driver_leave.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    override_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    override_reason = db.Column(db.String(512), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, server_default=false())

    driver_leave = db.relationship('DriverLeave', backref='overrides', lazy=True)
    created_by_user = db.relationship('User', foreign_keys=[created_by], lazy=True)

    __table_args__ = (
        Index('idx_leave_override_leave_id', 'driver_leave_id'),
        Index('idx_leave_override_date_time', 'override_date', 'start_time', 'end_time'),
        Index('idx_leave_override_leave_date', 'driver_leave_id', 'override_date'),
        Index('idx_leave_override_created_by', 'created_by'),
        db.UniqueConstraint(
            'driver_leave_id', 'override_date', 'start_time', 'end_time',
            name='uq_leave_override_no_duplicate'
        ),
    )

    @classmethod
    def query_active(cls):
        """Query active (non-deleted) overrides only"""
        return cls.query.filter_by(is_deleted=False)

    @classmethod
    def query_by_leave(cls, driver_leave_id):
        """Query all active overrides for a specific leave"""
        return cls.query_active().filter_by(driver_leave_id=driver_leave_id)

    @classmethod
    def query_by_date(cls, override_date):
        """Query all active overrides for a specific date"""
        return cls.query_active().filter_by(override_date=override_date)

    def overlaps_with(self, other_start_time, other_end_time):
        """
        Check if this override's time window overlaps with another time window
        on the same date.

        Overlap occurs if:
        - self.start_time < other_end_time AND
        - self.end_time > other_start_time

        Returns: True if overlap exists
        """
        return self.start_time < other_end_time and self.end_time > other_start_time

    def __repr__(self):
        return f'<LeaveOverride {self.id}: Leave {self.driver_leave_id} on {self.override_date} {self.start_time}-{self.end_time}>'
