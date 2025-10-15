from backend.models.settings import UserSettings
from backend.extensions import db

def get_user_settings(user_id: int) -> UserSettings:
    return UserSettings.query.filter_by(user_id=user_id).first()

def create_or_update_user_settings(user_id: int, new_preferences: dict) -> UserSettings:
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings:
        merged = dict(settings.preferences or {})
        merged.update(new_preferences)
        settings.preferences = merged
    else:
        settings = UserSettings(user_id=user_id, preferences=new_preferences)
        db.session.add(settings)
    db.session.commit()
    return settings

def delete_user_settings(user_id: int) -> bool:
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings:
        db.session.delete(settings)
        db.session.commit()
        return True
    return False

# Suggested code change incorporated
general_settings = {
    "company_name": "GrepX Pte Ltd",
    "company_address": "1 ROCHOR CANAL ROAD,\n#03-11, SIM LIM SQUARE,\nSINGAPORE 188504",
    "contact_number": "81123654",
    "email_id": "support@grepx.sg",
    "dark_mode": True,
    "language": "en",
    "timezone": "SGT"
}

photo_config = {
    "allowed_formats": "jpg,png",
    "max_photos": 2,
    "max_size_mb": 1,
    "stage": "OTS"
}