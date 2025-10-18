from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from marshmallow import fields
from backend.models.driver import Driver
from marshmallow_sqlalchemy import fields as ma_fields

class DriverSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Driver
        load_instance = True
    id = auto_field()
    name = auto_field()
    email = auto_field()
    mobile = auto_field()
    license_number = auto_field()
    vehicle_id = fields.Integer(allow_none=True)
    status = auto_field()
    is_deleted = auto_field()
    
    vehicle = ma_fields.Nested('VehicleSchema', dump_only=True)