from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from marshmallow import fields
from backend.models.contractor import Contractor

class ContractorSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Contractor
        load_instance = True
        include_relationships = True
    
    id = auto_field()
    name = auto_field()
    contact_person = auto_field()
    contact_number = auto_field()
    email = auto_field()
    status = auto_field()
    is_deleted = auto_field()