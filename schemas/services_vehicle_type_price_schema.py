from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from backend.models.ServicesVehicleTypePrice import ServicesVehicleTypePrice

class ServicesVehicleTypePriceSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = ServicesVehicleTypePrice
        load_instance = True
    id = auto_field()
    service_id = auto_field()
    vehicle_type_id = auto_field()
    price = auto_field()