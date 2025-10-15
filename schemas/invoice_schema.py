from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from backend.models.invoice import Invoice
from marshmallow_sqlalchemy import fields as ma_fields
from marshmallow import fields
from marshmallow import fields 


class InvoiceSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Invoice
        load_instance = True
    id = auto_field()
    customer_id = auto_field()
    date = auto_field()
    status = auto_field()
    total_amount = auto_field() 
    remaining_amount_invoice = auto_field() 

    
    jobs = ma_fields.Nested('JobSchema', many=True, dump_only=True)
