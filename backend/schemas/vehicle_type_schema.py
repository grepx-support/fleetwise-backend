from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from backend.models.vehicle_type import VehicleType

class VehicleTypeSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = VehicleType
        load_instance = True
    id = auto_field()
    name = auto_field()
    description = auto_field()
    status = auto_field()