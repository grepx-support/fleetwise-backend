from backend.extensions import db
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy import TypeDecorator

class JSONVariant(TypeDecorator):
    """A type decorator that selects the appropriate JSON type based on the database dialect."""
    impl = JSON

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB)
        else:
            return dialect.type_descriptor(JSON)

class JobAudit(db.Model):
    __tablename__ = 'job_audit'
    
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id', ondelete="CASCADE"), nullable=False)
    changed_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.current_timestamp())
    changed_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="SET NULL"), nullable=True)
    old_status = db.Column(db.String(50), nullable=True)
    new_status = db.Column(db.String(50), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    additional_data = db.Column(JSONVariant, nullable=True)
    
    # Relationships
    job = db.relationship('Job', backref='audit_records')
    changed_by_user = db.relationship('User', backref='job_audit_records')