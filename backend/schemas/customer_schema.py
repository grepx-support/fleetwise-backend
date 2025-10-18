from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from backend.models.customer import Customer
from backend.schemas.sub_customer_schema import SubCustomerSchema

class CustomerSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Customer
        load_instance = True
    id = auto_field()
    name = auto_field()
    email = auto_field()
    mobile = auto_field()
    company_name = auto_field()
    status = auto_field()
    address = auto_field()
    city = auto_field()
    state = auto_field()
    zip_code = auto_field()
    country = auto_field()
    type = auto_field()
    sub_customers = SubCustomerSchema(many=True)