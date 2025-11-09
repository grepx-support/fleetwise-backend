from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from backend.models.job import Job
from marshmallow_sqlalchemy import fields as ma_fields
from backend.schemas.customer_schema import CustomerSchema
from backend.schemas.driver_schema import DriverSchema
from backend.schemas.vehicle_schema import VehicleSchema
from backend.schemas.service_schema import ServiceSchema
from backend.schemas.invoice_schema import InvoiceSchema
from backend.schemas.contractor_schema import ContractorSchema
from marshmallow import fields
import json

class JobSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Job
        load_instance = True
        include_fk = True
    id = auto_field()
    customer_id = auto_field()
    sub_customer_name = auto_field()
    driver_id = auto_field()
    vehicle_id = auto_field()
    service_id = auto_field()
    contractor_id = auto_field()
    service_type = auto_field()
    pickup_location = auto_field()
    dropoff_location = auto_field()
    pickup_date = auto_field()
    pickup_time = auto_field()
    passenger_name = auto_field()
    passenger_email = auto_field()
    passenger_mobile = auto_field()
    booking_ref = auto_field()
    status = auto_field()
    # Handle extra_services as JSON data
    extra_services = fields.Method('get_extra_services', 'set_extra_services')
    additional_discount = auto_field()
    extra_charges = auto_field()
    base_price = auto_field()
    final_price = auto_field()
    invoice_id = auto_field()
    driver_commission = auto_field()
    penalty = auto_field()
    cash_to_collect = auto_field()
    customer_remark = auto_field()
    
    # Dropoff location fields
    dropoff_loc1 = auto_field()
    dropoff_loc2 = auto_field()
    dropoff_loc3 = auto_field()
    dropoff_loc4 = auto_field()
    dropoff_loc5 = auto_field()
    
    # Dropoff location price fields
    dropoff_loc1_price = auto_field()
    dropoff_loc2_price = auto_field()
    dropoff_loc3_price = auto_field()
    dropoff_loc4_price = auto_field()
    dropoff_loc5_price = auto_field()
    
    # Pickup location fields
    pickup_loc1 = auto_field()
    pickup_loc2 = auto_field()
    pickup_loc3 = auto_field()
    pickup_loc4 = auto_field()
    pickup_loc5 = auto_field()

    # Pickup location price fields
    pickup_loc1_price = auto_field()
    pickup_loc2_price = auto_field()
    pickup_loc3_price = auto_field()
    pickup_loc4_price = auto_field()
    pickup_loc5_price = auto_field()
    
    created_at = auto_field()
    updated_at = auto_field()
    
    # Add start_time and end_time fields
    start_time = auto_field()
    end_time = auto_field()
    
    # Add duration_minutes field
    duration_minutes = fields.Method('get_duration_minutes', dump_only=True)
    midnight_surcharge = auto_field()
    customer = ma_fields.Nested('CustomerSchema', dump_only=True)
    driver = ma_fields.Nested('DriverSchema', dump_only=True)
    vehicle = ma_fields.Nested('VehicleSchema', dump_only=True)
    service = ma_fields.Nested('ServiceSchema', dump_only=True)
    invoice = ma_fields.Nested('InvoiceSchema', exclude=('jobs',), dump_only=True)
    contractor = ma_fields.Nested('ContractorSchema', dump_only=True)
    
    # Computed fields for frontend compatibility
    customer_name = fields.Method('get_customer_name', dump_only=True)
    customer_email = fields.Method('get_customer_email', dump_only=True)
    customer_mobile = fields.Method('get_customer_mobile', dump_only=True)
    customer_reference = fields.Method('get_customer_reference', dump_only=True)
    
    # Vehicle computed fields
    vehicle_type_id = auto_field()
    vehicle_type_id = auto_field()
    vehicle_type = ma_fields.Nested('VehicleTypeSchema', dump_only=True)
    vehicle_number = fields.Method('get_vehicle_number', dump_only=True)
    vehicle_type_name = fields.Method('get_vehicle_type_name', dump_only=True)

    from backend.schemas.vehicle_type_schema import VehicleTypeSchema
    
    # Driver computed fields
    driver_contact = fields.Method('get_driver_contact', dump_only=True)
    driver_name = fields.Method('get_driver_name', dump_only=True)
    
    # Contractor computed fields
    contractor_name = fields.Method('get_contractor_name', dump_only=True)
    
    # Additional fields for frontend compatibility (not in Job model)
    payment_mode = fields.Method('get_payment_mode', dump_only=True)
    message = fields.Method('get_message', dump_only=True)
    remarks = fields.Method('get_remarks', dump_only=True)
    has_additional_stop = fields.Method('get_has_additional_stop', dump_only=True)
    additional_stops = fields.Method('get_additional_stops', dump_only=True)
    base_discount_percent = fields.Method('get_base_discount_percent', dump_only=True)
    customer_discount_percent = fields.Method('get_customer_discount_percent', dump_only=True)
    additional_discount_percent = fields.Method('get_additional_discount_percent', dump_only=True)
    invoice_number = fields.Method('get_invoice_number', dump_only=True)
    type_of_service = fields.Method('get_type_of_service', dump_only=True)
    
    # Add duration_str field
    duration_str = fields.Method('get_duration_str', dump_only=True)
    
    # Add status_history field for frontend validation
    status_history = fields.Method('get_status_history', dump_only=True)
    
    def get_extra_services(self, obj):
        """Get extra_services as JSON data for API response"""
        return obj.extra_services_data

    def set_extra_services(self, value):
        """Set extra_services from JSON data in API request"""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return []
        elif isinstance(value, list):
            return value
        else:
            return []

    def get_duration_str(self, obj):
        """Get duration_str from the Job model"""
        return obj.duration_str if obj.duration_str is not None else "0h 0m"
    
    def get_duration_minutes(self, obj):
        """Get duration_minutes from the Job model"""
        return obj.duration_minutes if obj.duration_minutes is not None else 0
    
    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else None
    
    def get_customer_email(self, obj):
        return obj.customer.email if obj.customer else None
    
    def get_customer_mobile(self, obj):
        return obj.customer.mobile if obj.customer else None
    
    def get_customer_reference(self, obj):
        # Since Customer model doesn't have reference field, return None or empty string
        return None
    

    def get_vehicle_type(self, obj):
        return obj.vehicle.type if obj.vehicle else None

    def get_vehicle_type_name(self, obj):
        # Return the name from the direct vehicle_type relationship
        if obj.vehicle_type:
            return obj.vehicle_type.name
        return None

    def get_vehicle_type_id(self, obj):
        # Canonical VehicleType id (requires vehicle.vehicle_type relationship)
        if obj.vehicle and hasattr(obj.vehicle, 'vehicle_type') and obj.vehicle.vehicle_type:
            return obj.vehicle.vehicle_type.id
        return None

    def get_vehicle_number(self, obj):
        return obj.vehicle.number if obj.vehicle else None
    
    def get_driver_contact(self, obj):
        return obj.driver.mobile if obj.driver else None
    
    def get_driver_name(self, obj):
        return obj.driver.name if obj.driver else None
    
    def get_contractor_name(self, obj):
        return obj.contractor.name if obj.contractor else None
    
    def get_type_of_service(self, obj):
        return obj.service_type
    
    # Default values for fields not in Job model
    def get_payment_mode(self, obj):
        return 'cash'
    
    def get_message(self, obj):
        return ''
    
    def get_remarks(self, obj):
        return ''
    
    def get_has_additional_stop(self, obj):
        return False
    
    def get_additional_stops(self, obj):
        return ''
    
    def get_base_discount_percent(self, obj):
        return 0
    
    def get_customer_discount_percent(self, obj):
        return 0
    
    def get_additional_discount_percent(self, obj):
        return 0
    
    def get_invoice_number(self, obj):
        return ''
    
    def get_status_history(self, obj):
        """Get recent status history for frontend validation"""
        try:
            from backend.models.job_audit import JobAudit
            from sqlalchemy import desc
            
            # Get recent audit records for this job
            recent_audits = JobAudit.query.filter_by(job_id=obj.id)\
                .filter(JobAudit.new_status.isnot(None))\
                .order_by(desc(JobAudit.changed_at))\
                .limit(10)\
                .all()
            
            # Format for frontend
            status_history = [
                {
                    'timestamp': audit.changed_at.isoformat() if audit.changed_at else None,
                    'status': audit.new_status
                }
                for audit in recent_audits
            ]
            
            return status_history
        except Exception as e:
            # Return empty array if there's any error
            return []