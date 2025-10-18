from datetime import datetime
from backend.extensions import db

class DriverRemark(db.Model):
    __tablename__ = "driver_remark"

    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id", ondelete="CASCADE"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("job.id", ondelete="CASCADE"), nullable=False)  # linked to job
    remark = db.Column(db.Text, nullable=False)
    # status = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    driver = db.relationship("Driver", back_populates="remarks")
    job = db.relationship("Job", back_populates="driver_remarks")


