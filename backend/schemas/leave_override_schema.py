from marshmallow import Schema, fields, validate, validates, validates_schema, ValidationError


class LeaveOverrideSchema(Schema):
    """
    Schema for serializing/deserializing LeaveOverride model.
    """
    id = fields.Int(dump_only=True)
    driver_leave_id = fields.Int(required=True, validate=validate.Range(min=1))
    override_date = fields.Date(required=True)
    start_time = fields.Time(required=True)  # HH:MM:SS format
    end_time = fields.Time(required=True)    # HH:MM:SS format
    override_reason = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=512)
    )

    # Read-only fields
    created_by = fields.Int(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    is_deleted = fields.Bool(dump_only=True)

    # Nested relationships (for detailed views)
    created_by_user = fields.Nested('UserSchema', dump_only=True, only=['id', 'email', 'name'])
    driver_leave = fields.Nested('DriverLeaveSchema', dump_only=True, only=['id', 'driver_id', 'start_date', 'end_date', 'status'])

    @validates('override_reason')
    def validate_reason_not_empty(self, value, **kwargs):
        """Ensure reason is not just whitespace"""
        if not value or not value.strip():
            raise ValidationError("override_reason cannot be empty or whitespace only")

    @validates_schema
    def validate_times(self, data, **kwargs):
        """Validate that start_time < end_time"""
        if 'start_time' in data and 'end_time' in data:
            if data['start_time'] >= data['end_time']:
                raise ValidationError(
                    {'end_time': f"end_time ({data['end_time']}) must be after start_time ({data['start_time']})"}
                )


class LeaveOverrideCreateSchema(Schema):
    """
    Schema for creating a new leave override.
    """
    override_date = fields.Date(required=True)
    start_time = fields.Time(required=True, format='%H:%M:%S')
    end_time = fields.Time(required=True, format='%H:%M:%S')
    override_reason = fields.Str(required=True, validate=validate.Length(min=1, max=512))

    @validates('override_reason')
    def validate_reason_not_empty(self, value, **kwargs):
        if not value or not value.strip():
            raise ValidationError("override_reason cannot be empty")

    @validates_schema
    def validate_times(self, data, **kwargs):
        if 'start_time' in data and 'end_time' in data:
            if data['start_time'] >= data['end_time']:
                raise ValidationError(
                    {'end_time': 'end_time must be after start_time'}
                )


class LeaveOverrideBulkCreateSchema(Schema):
    """
    Schema for bulk creating leave overrides for multiple drivers.
    """
    driver_leave_ids = fields.List(
        fields.Int(validate=validate.Range(min=1)),
        required=True,
        validate=validate.Length(min=1, max=100)
    )
    override_date = fields.Date(required=True)
    start_time = fields.Time(required=True, format='%H:%M:%S')
    end_time = fields.Time(required=True, format='%H:%M:%S')
    override_reason = fields.Str(required=True, validate=validate.Length(min=1, max=512))

    @validates('override_reason')
    def validate_reason_not_empty(self, value, **kwargs):
        if not value or not value.strip():
            raise ValidationError("override_reason cannot be empty")

    @validates_schema
    def validate_times(self, data, **kwargs):
        if 'start_time' in data and 'end_time' in data:
            if data['start_time'] >= data['end_time']:
                raise ValidationError(
                    {'end_time': 'end_time must be after start_time'}
                )

    @validates('driver_leave_ids')
    def validate_leave_ids_not_empty(self, value, **kwargs):
        if not value:
            raise ValidationError("driver_leave_ids cannot be empty")


class LeaveOverrideUpdateSchema(Schema):
    """
    Schema for updating a leave override.
    Note: Only specific fields can be updated.
    """
    override_reason = fields.Str(validate=validate.Length(min=1, max=512))

    @validates('override_reason')
    def validate_reason_not_empty(self, value, **kwargs):
        if value and not value.strip():
            raise ValidationError("override_reason cannot be empty or whitespace only")


class AvailabilityWindowSchema(Schema):
    """
    Schema for displaying availability windows (overrides) on calendar.
    Used for frontend calendar rendering.
    """
    id = fields.Int()
    start_time = fields.Time()
    end_time = fields.Time()
    reason = fields.Str()
    created_by = fields.Str()
