import logging
from datetime import datetime, time
from sqlalchemy import and_, or_
from backend.extensions import db
from backend.models.leave_override import LeaveOverride
from backend.models.driver_leave import DriverLeave
from backend.models.user import User
from backend.services.push_notification_service import PushNotificationService

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Custom exception for service-layer errors"""
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class LeaveOverrideService:
    """
    Service layer for managing driver leave overrides.

    Business Rules:
    1. Override can only be created on APPROVED leaves
    2. Override date must fall within leave's start_date to end_date
    3. start_time < end_time (both on same day)
    4. No overlapping time windows on same leave for same date
    5. Overrides are reversible (can be deleted)
    """

    @staticmethod
    def create_override(driver_leave_id, override_date, start_time, end_time, override_reason, created_by_id):
        """Create a new leave override with full validation."""
        leave = DriverLeave.query_active().filter_by(id=driver_leave_id).first()
        if not leave:
            raise ServiceError(f"Leave {driver_leave_id} not found")

        if leave.status != 'approved':
            raise ServiceError(f"Can only create overrides on APPROVED leaves. Current status: {leave.status}")

        user = User.query.filter_by(id=created_by_id).first()
        if not user:
            raise ServiceError(f"User {created_by_id} not found")

        if isinstance(start_time, str):
            try:
                start_time = datetime.strptime(start_time, '%H:%M:%S').time()
            except ValueError:
                raise ServiceError("start_time must be in HH:MM:SS format")

        if isinstance(end_time, str):
            try:
                end_time = datetime.strptime(end_time, '%H:%M:%S').time()
            except ValueError:
                raise ServiceError("end_time must be in HH:MM:SS format")

        if start_time >= end_time:
            raise ServiceError(f"start_time must be before end_time")

        if not (leave.start_date <= override_date <= leave.end_date):
            raise ServiceError(f"Override date {override_date} must be within leave period {leave.start_date} to {leave.end_date}")

        if not override_reason or not override_reason.strip():
            raise ServiceError("override_reason cannot be empty")

        reason = override_reason.strip()
        if len(reason) > 512:
            raise ServiceError("override_reason exceeds maximum length of 512 characters")

        # Check for overlapping overrides
        existing_overrides = LeaveOverride.query_active().filter(
            and_(
                LeaveOverride.driver_leave_id == driver_leave_id,
                LeaveOverride.override_date == override_date
            )
        ).all()

        for existing in existing_overrides:
            if existing.overlaps_with(start_time, end_time):
                raise ServiceError(f"Override time window {start_time}-{end_time} overlaps with existing override on {override_date}")

        try:
            override = LeaveOverride(
                driver_leave_id=driver_leave_id,
                override_date=override_date,
                start_time=start_time,
                end_time=end_time,
                override_reason=reason,
                created_by=created_by_id
            )
            db.session.add(override)
            db.session.commit()
            logger.info(f"Override created: Leave {driver_leave_id}, Date {override_date}, Time {start_time}-{end_time}")

            # Send notification to driver about the override
            try:
                driver = leave.driver
                if driver and driver.notification_token:
                    notification_title = "Leave Override Created"
                    notification_body = (
                        f"An override has been created for your leave on {override_date}. "
                        f"Available from {start_time.strftime('%H:%M')} to {end_time.strftime('%H:%M')}. "
                        f"Reason: {reason}"
                    )
                    notification_data = {
                        'override_id': str(override.id),
                        'leave_id': str(driver_leave_id),
                        'override_date': str(override_date),
                        'created_by': user.name or user.email
                    }

                    PushNotificationService.send(
                        token=driver.notification_token,
                        title=notification_title,
                        body=notification_body,
                        data=notification_data
                    )
                    logger.info(f"Notification sent to driver {driver.id} about override {override.id}")
            except Exception as notification_error:
                logger.warning(f"Failed to send notification to driver: {notification_error}")

            return override
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating leave override: {e}")
            raise ServiceError(f"Failed to create override: {str(e)}")

    @staticmethod
    def get_override(override_id):
        """Retrieve a single override by ID."""
        return LeaveOverride.query_active().filter_by(id=override_id).first()

    @staticmethod
    def get_overrides_for_leave(driver_leave_id):
        """Retrieve all active overrides for a specific leave, ordered by date and time."""
        return LeaveOverride.query_by_leave(driver_leave_id).order_by(
            LeaveOverride.override_date,
            LeaveOverride.start_time
        ).all()

    @staticmethod
    def get_overrides_for_date(override_date):
        """Retrieve all active overrides for a specific date."""
        return LeaveOverride.query_by_date(override_date).all()

    @staticmethod
    def get_overrides_for_leave_and_date(driver_leave_id, override_date):
        """Retrieve all active overrides for a specific leave on a specific date."""
        return LeaveOverride.query_active().filter(
            and_(
                LeaveOverride.driver_leave_id == driver_leave_id,
                LeaveOverride.override_date == override_date
            )
        ).order_by(LeaveOverride.start_time).all()

    @staticmethod
    def delete_override(override_id):
        """Delete (soft delete) an override. Returns True if successful, False if not found."""
        override = LeaveOverride.query_active().filter_by(id=override_id).first()
        if not override:
            return False

        try:
            override.is_deleted = True
            override.updated_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"Override {override_id} deleted")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting override {override_id}: {e}")
            raise ServiceError(f"Failed to delete override: {str(e)}")

    @staticmethod
    def delete_override_by_leave(driver_leave_id):
        """Delete all active overrides for a specific leave. Returns count of deleted overrides."""
        try:
            overrides = LeaveOverride.query_by_leave(driver_leave_id).all()
            count = 0
            for override in overrides:
                override.is_deleted = True
                override.updated_at = datetime.utcnow()
                count += 1

            if count > 0:
                db.session.commit()
                logger.info(f"Deleted {count} overrides for leave {driver_leave_id}")

            return count
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting overrides for leave {driver_leave_id}: {e}")
            raise ServiceError(f"Failed to delete overrides: {str(e)}")

    @staticmethod
    def bulk_create_overrides(driver_leave_ids, override_date, start_time, end_time, override_reason, created_by_id):
        """Create overrides for multiple leaves. Returns dict with success and failed lists."""
        if not driver_leave_ids:
            raise ServiceError("driver_leave_ids list cannot be empty")

        if not isinstance(driver_leave_ids, list):
            raise ServiceError("driver_leave_ids must be a list")

        if len(driver_leave_ids) > 100:
            raise ServiceError("Cannot bulk create more than 100 overrides at once")

        success = []
        failed = []

        for leave_id in driver_leave_ids:
            try:
                override = LeaveOverrideService.create_override(
                    driver_leave_id=leave_id,
                    override_date=override_date,
                    start_time=start_time,
                    end_time=end_time,
                    override_reason=override_reason,
                    created_by_id=created_by_id
                )
                success.append(override)
            except ServiceError as e:
                failed.append({
                    'driver_leave_id': leave_id,
                    'error': e.message
                })
                logger.warning(f"Failed to create override for leave {leave_id}: {e.message}")

        return {
            'success': success,
            'failed': failed
        }

    @staticmethod
    def is_driver_available_during_override(driver_leave_id, check_datetime):
        """Check if driver has an active override covering the specified datetime."""
        check_date = check_datetime.date()
        check_time = check_datetime.time()

        override = LeaveOverride.query_active().filter(
            and_(
                LeaveOverride.driver_leave_id == driver_leave_id,
                LeaveOverride.override_date == check_date,
                LeaveOverride.start_time <= check_time,
                LeaveOverride.end_time > check_time
            )
        ).first()

        return override is not None

    @staticmethod
    def get_availability_windows(driver_leave_id, override_date):
        """Get all availability windows (overrides) for a leave on a specific date. Formatted for calendar display."""
        overrides = LeaveOverrideService.get_overrides_for_leave_and_date(driver_leave_id, override_date)
        return [
            {
                'id': override.id,
                'start_time': override.start_time,
                'end_time': override.end_time,
                'reason': override.override_reason,
                'created_by': override.created_by_user.email if override.created_by_user else 'Unknown'
            }
            for override in overrides
        ]
