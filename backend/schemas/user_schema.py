from marshmallow import Schema, fields, validate
from marshmallow_sqlalchemy import fields as ma_fields

class UserSchema(Schema):
    id = fields.Int(dump_only=True)
    email = fields.Email(required=True)
    password = fields.Str(load_only=True, required=True)
    name = fields.Str(allow_none=True, validate=validate.Length(max=255))  # New name field with length validation
    active = fields.Bool()
    fs_uniquifier = fields.Str()
    customer_id = fields.Int(allow_none=True)
    driver_id = fields.Int(allow_none=True)
    roles = fields.List(fields.Nested(lambda: RoleSchema(exclude=("users",))), dump_only=True)
    role_names = fields.List(fields.Str(), load_only=True)  # For deserializing role names
    driver = ma_fields.Nested('DriverSchema', dump_only=True)
    
from backend.schemas.role_schema import RoleSchema  # Avoid circular import