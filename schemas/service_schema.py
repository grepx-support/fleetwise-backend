from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from marshmallow import fields
from backend.models.service import Service

class ServiceSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Service
        load_instance = True
    id = auto_field()
    name = auto_field(required=True)
    description = auto_field()
    status = auto_field(required=True)