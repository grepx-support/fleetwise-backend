from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.types import JSON
from backend.extensions import db
from datetime import datetime

class SystemSettings(db.Model):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True)
    setting_key = Column(String(100), unique=True, nullable=False)
    setting_value = Column(JSON)
    updated_by = Column(Integer, ForeignKey('user.id'))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<SystemSettings id={self.id} setting_key={self.setting_key}>"