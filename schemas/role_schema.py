from marshmallow import Schema, fields

class RoleSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    description = fields.Str()
    users = fields.List(fields.Nested(lambda: UserSchema(exclude=("roles",)), dump_only=True))

from backend.schemas.user_schema import UserSchema  # Avoid circular import 