from marshmallow import fields, Schema, ValidationError

class CustomerServicePricingSchema(Schema):
    """Schema for customer service pricing"""
    
    # Input/Output fields using exact column names
    id = fields.Int(dump_only=True)
    cust_id = fields.Int(required=True)
    service_id = fields.Int(required=True)
    vehicle_type_id = fields.Int(required=True)
    price = fields.Float(allow_none=True)
