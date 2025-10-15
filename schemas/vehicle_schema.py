from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from backend.models.vehicle import Vehicle

class VehicleSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Vehicle
        load_instance = True
    id = auto_field()
    name = auto_field()
    number = auto_field()
    type = auto_field()
    status = auto_field() 