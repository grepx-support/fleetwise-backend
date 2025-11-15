from marshmallow_sqlalchemy import SQLAlchemyAutoSchema, auto_field
from marshmallow import fields, validates, ValidationError
from backend.models.driver_leave import DriverLeave
from backend.models.job_reassignment import JobReassignment
from marshmallow_sqlalchemy import fields as ma_fields
from datetime import datetime

class DriverLeaveSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = DriverLeave
        load_instance = True
        include_fk = True

    id = auto_field(dump_only=True)
    driver_id = auto_field()
    leave_type = auto_field()
    start_date = auto_field()
    end_date = auto_field()
    status = auto_field()
    reason = auto_field()
    created_by = auto_field()
    created_at = auto_field(dump_only=True)
    updated_at = auto_field(dump_only=True)
    is_deleted = auto_field()

    # Nested relationships
    driver = ma_fields.Nested('DriverSchema', dump_only=True)
    created_by_user = ma_fields.Nested('UserSchema', dump_only=True, exclude=['password', 'fs_uniquifier'])

    @validates('leave_type')
    def validate_leave_type(self, value):
        """Validate leave type is one of the allowed values"""
        allowed_types = ['sick_leave', 'vacation', 'personal', 'emergency']
        if value not in allowed_types:
            raise ValidationError(f"Leave type must be one of: {', '.join(allowed_types)}")
        return value

    @validates('status')
    def validate_status(self, value):
        """Validate status is one of the allowed values"""
        allowed_statuses = ['approved', 'pending', 'rejected', 'cancelled']
        if value not in allowed_statuses:
            raise ValidationError(f"Status must be one of: {', '.join(allowed_statuses)}")
        return value


class JobReassignmentSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = JobReassignment
        load_instance = True
        include_fk = True

    id = auto_field(dump_only=True)
    job_id = auto_field()
    driver_leave_id = auto_field()
    original_driver_id = auto_field()
    original_vehicle_id = auto_field()
    original_contractor_id = auto_field()
    reassignment_type = auto_field()
    new_driver_id = auto_field()
    new_vehicle_id = auto_field()
    new_contractor_id = auto_field()
    notes = auto_field()
    reassigned_by = auto_field()
    reassigned_at = auto_field(dump_only=True)
    is_deleted = auto_field()

    # Nested relationships
    job = ma_fields.Nested('JobSchema', dump_only=True)
    driver_leave = ma_fields.Nested('DriverLeaveSchema', dump_only=True, exclude=['job_reassignments'])
    original_driver = ma_fields.Nested('DriverSchema', dump_only=True)
    new_driver = ma_fields.Nested('DriverSchema', dump_only=True)
    reassigned_by_user = ma_fields.Nested('UserSchema', dump_only=True, exclude=['password', 'fs_uniquifier'])

    @validates('reassignment_type')
    def validate_reassignment_type(self, value):
        """Validate reassignment type is one of the allowed values"""
        allowed_types = ['driver', 'vehicle', 'contractor']
        if value not in allowed_types:
            raise ValidationError(f"Reassignment type must be one of: {', '.join(allowed_types)}")
        return value


# Schema for creating a new leave with affected jobs response
class DriverLeaveCreateResponseSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = DriverLeave
        load_instance = True

    id = auto_field()
    driver_id = auto_field()
    leave_type = auto_field()
    start_date = auto_field()
    end_date = auto_field()
    status = auto_field()
    reason = auto_field()

    # Additional fields for response
    affected_jobs = fields.List(fields.Nested('JobSchema'), dump_only=True)
    affected_jobs_count = fields.Integer(dump_only=True)
    requires_reassignment = fields.Boolean(dump_only=True)


# Schema for job reassignment request
class JobReassignmentRequestSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = JobReassignment
        load_instance = False

    job_id = fields.Integer(required=True)
    reassignment_type = fields.String(required=True)
    new_driver_id = fields.Integer(allow_none=True)
    new_vehicle_id = fields.Integer(allow_none=True)
    new_contractor_id = fields.Integer(allow_none=True)
    notes = fields.String(allow_none=True)
