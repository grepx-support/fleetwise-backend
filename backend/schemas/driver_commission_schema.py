from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from backend.models.driver_commission_table import DriverCommissionTable

class DriverCommissionSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = DriverCommissionTable
        load_instance = True
    id = auto_field()
    driver_id = auto_field()
    job_type = auto_field()
    vehicle_type = auto_field()
    commission_amount = auto_field() 