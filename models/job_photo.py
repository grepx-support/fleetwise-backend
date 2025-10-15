from datetime import datetime
from backend.extensions import db

class JobPhoto(db.Model):
    __tablename__ = "job_photo"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("job.id", ondelete="CASCADE"), nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("driver.id", ondelete="SET NULL"), nullable=True, index=True)
    stage = db.Column(db.String(50), nullable=False)                # pickup, dropoff, incident, verification, etc.
    file_path = db.Column(db.String(255), nullable=False)           # local path (later can switch to S3 URL)
    file_size = db.Column(db.Integer)   
    file_hash = db.Column(db.String(64), nullable=False, index=True)  # in KB
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Add filename column for indexed lookups
    filename = db.Column(db.String(255), nullable=True)  # New column for indexed filename lookups


    # Relationships
    job = db.relationship("Job", backref=db.backref("photos", lazy="dynamic", cascade="all, delete-orphan"))
    driver = db.relationship("Driver", backref=db.backref("photos", lazy="dynamic"))

    def __repr__(self):
        return f"<JobPhoto job={self.job_id} stage={self.stage}>"