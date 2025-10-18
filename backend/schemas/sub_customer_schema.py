from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from backend.models.sub_customer import SubCustomer

class SubCustomerSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = SubCustomer
        load_instance = True
    id = auto_field()
    name = auto_field()
    customer_id = auto_field() 