from marshmallow import Schema, fields, post_load, validates, ValidationError
from backend.models.bill import Bill
# Removed BillItem import since you don't want to use it
from backend.models.job import Job
from backend.models.contractor import Contractor
from backend.models.driver import Driver
from backend.extensions import db

# Commented out BillItemSchema since you don't want to use BillItem
# class BillItemSchema(Schema):
#     id = fields.Int(dump_only=True)
#     bill_id = fields.Int(required=False)
#     job_id = fields.Int(required=True)
#     amount = fields.Decimal(as_string=True, required=True)
#     
#     job = fields.Nested('JobSchema', dump_only=True)

class BillSchema(Schema):
    id = fields.Int(dump_only=True)
    contractor_id = fields.Int(required=False, allow_none=True)
    date = fields.DateTime(dump_only=True)
    status = fields.Str(required=False)
    total_amount = fields.Decimal(as_string=True, dump_only=True)
    file_path = fields.Str(dump_only=True)
    
    contractor = fields.Nested('ContractorSchema', dump_only=True)
    driver = fields.Nested('DriverSchema', dump_only=True)  # Add driver relationship
    # Removed bill_items field since you don't want to use BillItem
    # bill_items = fields.Nested('BillItemSchema', many=True, dump_only=True)
    # Add jobs field to include job information
    jobs = fields.Nested('JobSchema', many=True, dump_only=True)
    
    @validates('contractor_id')
    def validate_contractor_exists(self, value):
        # Skip validation for driver bills (null contractor_id)
        if value is None:
            return

        contractor = Contractor.query.get(value)
        if not contractor:
            raise ValidationError(f'Contractor with id {value} does not exist.')
    
    @post_load
    def make_bill(self, data, **kwargs):
        return Bill(**data)