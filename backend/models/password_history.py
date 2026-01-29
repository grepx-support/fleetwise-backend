from datetime import datetime, timezone
from backend.extensions import db


class PasswordHistory(db.Model):
    """Model to store password history for users to prevent password reuse"""
    __tablename__ = 'password_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationship to user
    user = db.relationship('User', backref=db.backref('password_history', lazy='dynamic', cascade='all, delete-orphan'))

    def __init__(self, user_id, password_hash):
        """
        Create a new password history entry

        Args:
            user_id: The ID of the user
            password_hash: The hashed password to store
        """
        self.user_id = user_id
        self.password_hash = password_hash

    @classmethod
    def add_to_history(cls, user_id, password_hash, keep_last=5):
        """
        Add a password to history and maintain only the last N passwords

        Args:
            user_id: The ID of the user
            password_hash: The hashed password to store
            keep_last: Number of password history entries to keep (default: 5)
        """
        # Add new password to history
        new_entry = cls(user_id, password_hash)
        db.session.add(new_entry)

        # Get all history entries for this user, ordered by most recent first
        all_entries = cls.query.filter_by(user_id=user_id).order_by(cls.created_at.desc()).all()

        # If we have more than keep_last entries, delete the oldest ones
        if len(all_entries) >= keep_last:
            entries_to_delete = all_entries[keep_last - 1:]  # -1 because we just added one
            for entry in entries_to_delete:
                db.session.delete(entry)

    @classmethod
    def get_recent_passwords(cls, user_id, count=5):
        """
        Get the most recent password hashes for a user

        Args:
            user_id: The ID of the user
            count: Number of recent passwords to retrieve (default: 5)

        Returns:
            list: List of password hash strings
        """
        entries = cls.query.filter_by(user_id=user_id).order_by(cls.created_at.desc()).limit(count).all()
        return [entry.password_hash for entry in entries]

    def __repr__(self):
        return f'<PasswordHistory user_id={self.user_id} created_at={self.created_at}>'
