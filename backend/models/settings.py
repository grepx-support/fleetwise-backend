from sqlalchemy import Column, Integer, UniqueConstraint, ForeignKey
from sqlalchemy.types import JSON
from backend.extensions import db

class UserSettings(db.Model):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('user.id'), unique=True, nullable=False)
    preferences = Column(JSON, nullable=False)

    user = db.relationship('User', backref=db.backref('settings', uselist=False))

    __table_args__ = (
        UniqueConstraint('user_id', name='uq_user_settings_user_id'),
    )

    def __repr__(self):
        return f"<UserSettings id={self.id} user_id={self.user_id} preferences={self.preferences}>"