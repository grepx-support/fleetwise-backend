from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from backend.models.settings import UserSettings
from backend.schemas.user_schema import UserSchema
from marshmallow_sqlalchemy.fields import Nested

class UserSettingsSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = UserSettings
        load_instance = True
        include_fk = True

    user = Nested(UserSchema, only=("id", "email"), dump_only=True)