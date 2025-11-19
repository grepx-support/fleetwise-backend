import logging
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Any, Optional, Union
from backend.extensions import db
from backend.models.driver_leave import DriverLeave
from backend.models.job_reassignment import JobReassignment
from backend.models.job import Job
from backend.models.job_audit import JobAudit
from backend.models.driver import Driver
from flask_security import current_user

logger = logging.getLogger(__name__)


# Constants for job statuses
class JobStatus:
    """Job status constants"""
    NEW = 'new'
    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    OTW = 'otw'  # On The Way
    OTS = 'ots'  # On The Site
    POB = 'pob'  # Person On Board
    JC = 'jc'    # Job Completed
    SD = 'sd'    # Stand-Down
    CANCELED = 'canceled'

    # Status categories
    NOT_STARTED = [NEW, CONFIRMED]
    IN_PROGRESS = [OTW, OTS, POB]
    COMPLETED = [JC, SD, CANCELED]


class LeaveStatus:
    """Leave status constants"""
    APPROVED = 'approved'
    PENDING = 'pending'
    REJECTED = 'rejected'
    CANCELLED = 'cancelled'

    ALL = [APPROVED, PENDING, REJECTED, CANCELLED]


class LeaveType:
    """Leave type constants"""
    SICK_LEAVE = 'sick_leave'
    VACATION = 'vacation'
    PERSONAL = 'personal'
    EMERGENCY = 'emergency'

    ALL = [SICK_LEAVE, VACATION, PERSONAL, EMERGENCY]


class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def sanitize_string(value: Optional[str], max_length: int = 512, field_name: str = "field") -> Optional[str]:
    """
    Sanitize string input by stripping whitespace and validating length.

    Args:
        value: String to sanitize
        max_length: Maximum allowed length
        field_name: Name of field for error messages

    Returns:
        Sanitized string or None if input is None/empty

    Raises:
        ServiceError: If string exceeds max length
    """
    if value is None:
        return None

    # Strip whitespace
    sanitized = value.strip()

    # Return None for empty strings
    if not sanitized:
        return None

    # Validate length
    if len(sanitized) > max_length:
        raise ServiceError(f"{field_name} exceeds maximum length of {max_length} characters")

    return sanitized


class DriverLeaveService:
    @staticmethod
    def create_leave(
        driver_id: int,
        leave_type: str,
        start_date: Union[str, date],
        end_date: Union[str, date],
        reason: Optional[str] = None,
        status: str = 'approved',
        created_by: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create a new driver leave record.

        Args:
            driver_id: ID of the driver
            leave_type: Type of leave (sick_leave, vacation, personal, emergency)
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            reason: Optional reason for leave
            status: Leave status (default: approved)
            created_by: User ID who created the leave

        Returns:
            dict: Contains leave record and affected jobs information

        Raises:
            ServiceError: If validation fails
        """
        # Validate driver exists and is active
        driver = Driver.query_active().filter_by(id=driver_id).first()
        if not driver:
            raise ServiceError(f"Driver with ID {driver_id} not found or is inactive")

        # Convert string dates to date objects if necessary
        if isinstance(start_date, str):
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
            except ValueError:
                raise ServiceError("Invalid start_date format. Use YYYY-MM-DD")
        else:
            start_dt = start_date

        if isinstance(end_date, str):
            try:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                raise ServiceError("Invalid end_date format. Use YYYY-MM-DD")
        else:
            end_dt = end_date

        if end_dt < start_dt:
            raise ServiceError("End date cannot be before start date")

        # Validate dates are not in the past
        today = datetime.now(timezone.utc).date()
        if start_dt < today:
            raise ServiceError(f"Cannot create leave: start date ({start_dt}) is in the past")
        if end_dt < today:
            raise ServiceError(f"Cannot create leave: end date ({end_dt}) is in the past")

        # Validate leave type
        if leave_type not in LeaveType.ALL:
            raise ServiceError(f"Invalid leave type. Must be one of: {', '.join(LeaveType.ALL)}")

        # Sanitize string inputs
        reason = sanitize_string(reason, max_length=512, field_name="reason")

        # Validate status
        if status not in LeaveStatus.ALL:
            raise ServiceError(f"Invalid status. Must be one of: {', '.join(LeaveStatus.ALL)}")

        # Check for overlapping leaves with row-level locking (prevents race conditions)
        overlapping_leaves = DriverLeave.query_active().filter(
            DriverLeave.driver_id == driver_id,
            DriverLeave.status.in_([LeaveStatus.APPROVED, LeaveStatus.PENDING]),
            db.or_(
                # New leave starts during existing leave
                db.and_(
                    DriverLeave.start_date <= start_dt,
                    DriverLeave.end_date >= start_dt
                ),
                # New leave ends during existing leave
                db.and_(
                    DriverLeave.start_date <= end_dt,
                    DriverLeave.end_date >= end_dt
                ),
                # New leave completely contains existing leave
                db.and_(
                    DriverLeave.start_date >= start_dt,
                    DriverLeave.end_date <= end_dt
                )
            )
        ).with_for_update().first()  # Added row-level locking

        if overlapping_leaves:
            raise ServiceError(
                f"Driver already has a leave scheduled from {overlapping_leaves.start_date} to {overlapping_leaves.end_date}"
            )

        # Force status to 'pending' if there are affected jobs and status is 'approved'
        # This prevents approving leaves without reassigning jobs first
        effective_status = status
        if status == LeaveStatus.APPROVED:
            # Check if there would be affected jobs
            affected_jobs_check = DriverLeaveService.get_affected_jobs(driver_id, start_dt, end_dt)
            if affected_jobs_check:
                effective_status = LeaveStatus.PENDING
                logger.warning(
                    f"Leave creation: status changed from '{LeaveStatus.APPROVED}' to '{LeaveStatus.PENDING}' "
                    f"because {len(affected_jobs_check)} affected jobs need reassignment"
                )

        # Create leave record with date objects
        leave = DriverLeave(
            driver_id=driver_id,
            leave_type=leave_type,
            start_date=start_dt,  # Use date object
            end_date=end_dt,      # Use date object
            status=effective_status,  # Use validated status
            reason=reason,
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        db.session.add(leave)
        db.session.flush()  # Get the leave ID

        # Find affected jobs
        affected_jobs = DriverLeaveService.get_affected_jobs(driver_id, start_dt, end_dt)

        db.session.commit()

        logger.info(f"Created leave ID {leave.id} for driver {driver_id} from {start_dt} to {end_dt}")

        return {
            'leave': leave,
            'affected_jobs': affected_jobs,
            'affected_jobs_count': len(affected_jobs),
            'requires_reassignment': len(affected_jobs) > 0
        }

    @staticmethod
    def get_leave_by_id(leave_id: int) -> DriverLeave:
        """
        Get a driver leave by ID.

        Args:
            leave_id: ID of the leave

        Returns:
            DriverLeave: The leave object

        Raises:
            ServiceError: If leave not found
        """
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            raise ServiceError(f"Leave with ID {leave_id} not found")
        return leave

    @staticmethod
    def get_affected_jobs(driver_id: int, start_date: Union[str, date], end_date: Union[str, date]) -> List[Job]:
        """
        Get all jobs assigned to a driver during the leave period.

        Args:
            driver_id: ID of the driver
            start_date: Start date as string (YYYY-MM-DD) or date object
            end_date: End date as string (YYYY-MM-DD) or date object

        Returns:
            list: List of Job objects that need reassignment
        """
        # Convert to date objects if strings
        if isinstance(start_date, str):
            start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_dt = start_date

        if isinstance(end_date, str):
            end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end_dt = end_date

        active_statuses = ['new', 'pending', 'confirmed', 'otw', 'ots', 'pob']

        # Job.pickup_date is stored as String(32) in YYYY-MM-DD format
        # Convert date objects to string for comparison
        affected_jobs = Job.query_active().filter(
            Job.driver_id == driver_id,
            Job.pickup_date >= start_dt.strftime('%Y-%m-%d'),
            Job.pickup_date <= end_dt.strftime('%Y-%m-%d'),
            Job.status.in_(active_statuses)
        ).order_by(Job.pickup_date, Job.pickup_time).all()

        return affected_jobs

    @staticmethod
    def reassign_jobs(
        leave_id: int,
        reassignments: List[Dict[str, Any]],
        reassigned_by: Optional[int] = None,
        atomic: bool = True
    ) -> Dict[str, Any]:
        """
        Reassign jobs during a driver's leave period with proper transaction handling.

        Args:
            leave_id: ID of the driver leave record
            reassignments: List of dicts with job reassignment details
                Each dict should contain:
                - job_id: ID of the job to reassign (required)
                - new_driver_id: New driver ID (optional, defaults to 0/null if not provided)
                - new_vehicle_id: New vehicle ID (optional, defaults to 0/null if not provided)
                - new_contractor_id: New contractor ID (optional, defaults to 0/null if not provided)
                - notes: Reassignment notes (optional)
                Note: Missing fields automatically default to 0 (which becomes NULL in database)
            reassigned_by: User ID who performed the reassignment
            atomic: If True (default), rollback all changes if any reassignment fails.
                   If False, commit successful reassignments even if some fail.

        Returns:
            dict: Summary of reassignment results with success/failed lists

        Raises:
            ServiceError: If validation fails or if atomic=True and any reassignment fails
        """
        # Validate leave exists
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            raise ServiceError(f"Leave with ID {leave_id} not found")

        results = {
            'success': [],
            'failed': [],
            'skipped': [],
            'total': len(reassignments)
        }

        # Use savepoint for atomic operations
        savepoint = None
        if atomic:
            savepoint = db.session.begin_nested()

        try:
            for reassignment_data in reassignments:
                try:
                    # Validate job exists and belongs to the driver on leave
                    job_id = reassignment_data.get('job_id')
                    job = Job.query_active().filter_by(id=job_id).first()

                    if not job:
                        raise ServiceError(f"Job {job_id} not found")

                    if job.driver_id != leave.driver_id:
                        raise ServiceError(f"Job {job_id} is not assigned to driver {leave.driver_id}")

                    # Store original assignment
                    original_driver_id = job.driver_id
                    original_vehicle_id = job.vehicle_id
                    original_contractor_id = job.contractor_id

                    # Get reassignment fields - set to 0 if not provided
                    new_driver_id = reassignment_data.get('new_driver_id', 0)
                    new_vehicle_id = reassignment_data.get('new_vehicle_id', 0)
                    new_contractor_id = reassignment_data.get('new_contractor_id', 0)

                    # Define status categories using constants
                    not_started_statuses = JobStatus.NOT_STARTED
                    in_progress_statuses = JobStatus.IN_PROGRESS

                    # Status-based reassignment logic
                    if job.status in not_started_statuses:
                        # Jobs not started: Allow full reassignment (can set to NULL)
                        new_driver_value = new_driver_id if new_driver_id > 0 else None
                        new_vehicle_value = new_vehicle_id if new_vehicle_id > 0 else None
                        new_contractor_value = new_contractor_id if new_contractor_id > 0 else None
                    elif job.status in in_progress_statuses:
                        # Jobs in progress: Handle contractor assignment specially
                        if new_contractor_id > 0:
                            # When assigning to contractor, clear driver and vehicle
                            new_driver_value = None
                            new_vehicle_value = None
                            new_contractor_value = new_contractor_id
                        else:
                            # Preserve original values if not explicitly provided
                            new_driver_value = new_driver_id if new_driver_id > 0 else original_driver_id
                            new_vehicle_value = new_vehicle_id if new_vehicle_id > 0 else original_vehicle_id
                            new_contractor_value = original_contractor_id
                    else:
                        # For other statuses (canceled, jc, sd, etc.), use default behavior
                        new_driver_value = new_driver_id if new_driver_id > 0 else None
                        new_vehicle_value = new_vehicle_id if new_vehicle_id > 0 else None
                        new_contractor_value = new_contractor_id if new_contractor_id > 0 else None

                    # Check if at least one field is being updated
                    is_driver_changed = new_driver_value != original_driver_id
                    is_vehicle_changed = new_vehicle_value != original_vehicle_id
                    is_contractor_changed = new_contractor_value != original_contractor_id

                    # For in-progress jobs, if no new values provided (all 0), skip this job - no changes needed
                    if job.status in in_progress_statuses and new_driver_id == 0 and new_vehicle_id == 0 and new_contractor_id == 0:
                        # Skip this job - it's in progress and no reassignment values provided
                        results['skipped'].append({
                            'job_id': job_id,
                            'reason': f"Job is in-progress (status: {job.status}) and no reassignment values provided. Original assignment preserved.",
                            'status': job.status
                        })
                        continue

                    if not (is_driver_changed or is_vehicle_changed or is_contractor_changed):
                        raise ServiceError(
                            f"Job {job_id}: No changes detected. At least one field must be different from current assignment. "
                            f"Current: driver={original_driver_id}, vehicle={original_vehicle_id}, contractor={original_contractor_id}"
                        )

                    # Store old status for audit trail
                    old_status = job.status

                    # Assign all 3 fields to the job
                    job.driver_id = new_driver_value
                    job.vehicle_id = new_vehicle_value
                    job.contractor_id = new_contractor_value
                    job.updated_at = datetime.now(timezone.utc)

                    # Update job status based on contractor assignment (only for basic statuses)
                    if job.status in not_started_statuses:  # ['new', 'confirmed']
                        # Check if contractor is assigned
                        has_contractor = new_contractor_value is not None and new_contractor_value > 0

                        if has_contractor:
                            job.status = JobStatus.CONFIRMED  # Has contractor = confirmed
                        else:
                            job.status = JobStatus.PENDING    # No contractor = pending
                    # For in-progress jobs (otw, ots, pob), never change status
                    elif job.status in in_progress_statuses:
                        pass  # Status unchanged

                    # Create job audit record for every reassignment
                    status_changed = old_status != job.status
                    reason = f"Job reassigned due to driver leave (Leave ID: {leave_id})"
                    if status_changed:
                        reason += f". Status changed from '{old_status}' to '{job.status}'"

                    job_audit = JobAudit(
                        job_id=job_id,
                        changed_by=reassigned_by,
                        old_status=old_status,
                        new_status=job.status,
                        reason=reason,
                        additional_data={
                            'driver_leave_id': leave_id,
                            'reassignment_type': 'driver_leave',
                            'original_driver_id': original_driver_id,
                            'original_vehicle_id': original_vehicle_id,
                            'original_contractor_id': original_contractor_id,
                            'new_driver_id': new_driver_value,
                            'new_vehicle_id': new_vehicle_value,
                            'new_contractor_id': new_contractor_value,
                            'status_changed': status_changed
                        }
                    )
                    db.session.add(job_audit)

                    # Sanitize notes field
                    notes = sanitize_string(reassignment_data.get('notes'), max_length=512, field_name="notes")

                    # Create reassignment audit record
                    reassignment = JobReassignment(
                        job_id=job_id,
                        driver_leave_id=leave_id,
                        original_driver_id=original_driver_id,
                        original_vehicle_id=original_vehicle_id,
                        original_contractor_id=original_contractor_id,
                        new_driver_id=new_driver_id if new_driver_id > 0 else None,
                        new_vehicle_id=new_vehicle_id if new_vehicle_id > 0 else None,
                        new_contractor_id=new_contractor_id if new_contractor_id > 0 else None,
                        notes=notes,
                        reassigned_by=reassigned_by,
                        reassigned_at=datetime.now(timezone.utc)
                    )

                    db.session.add(reassignment)

                    results['success'].append({
                        'job_id': job_id,
                        'message': f"Job {job_id} successfully reassigned"
                    })

                    logger.info(f"Job {job_id} reassigned successfully")

                except ServiceError as e:
                    results['failed'].append({
                        'job_id': reassignment_data.get('job_id'),
                        'error': str(e)
                    })
                    logger.error(f"Failed to reassign job {reassignment_data.get('job_id')}: {str(e)}")

                    if atomic:
                        # Rollback entire transaction on first failure
                        if savepoint:
                            savepoint.rollback()
                        raise ServiceError(f"Atomic reassignment failed: {str(e)}. All changes rolled back.")
                    # If not atomic, continue with next reassignment
                    continue

                except Exception as e:
                    results['failed'].append({
                        'job_id': reassignment_data.get('job_id'),
                        'error': str(e)
                    })
                    logger.error(f"Unexpected error reassigning job {reassignment_data.get('job_id')}: {str(e)}")

                    if atomic:
                        # Rollback entire transaction on unexpected error
                        if savepoint:
                            savepoint.rollback()
                        raise ServiceError(f"Atomic reassignment failed: {str(e)}. All changes rolled back.")
                    # If not atomic, continue with next reassignment
                    continue

            # If we get here and atomic mode is on, commit the nested transaction
            db.session.commit()

            return results

        except ServiceError:
            # Re-raise ServiceError (already logged)
            db.session.rollback()
            raise
        except Exception as e:
            # Unexpected error in outer try block
            db.session.rollback()
            logger.error(f"Fatal error in reassign_jobs: {str(e)}", exc_info=True)
            raise ServiceError(f"Reassignment transaction failed: {str(e)}")

    @staticmethod
    def check_driver_on_leave(driver_id: int, date_str: Union[str, date]):
        """
        Check if a driver is on approved leave on a specific date.

        Args:
            driver_id: ID of the driver
            date_str: Date to check as string (YYYY-MM-DD) or date object

        Returns:
            DriverLeave object if driver is on leave, None otherwise
        """
        # Convert to date object if string
        if isinstance(date_str, str):
            check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            check_date = date_str

        leave = DriverLeave.query_active().filter(
            DriverLeave.driver_id == driver_id,
            DriverLeave.status == LeaveStatus.APPROVED,
            DriverLeave.start_date <= check_date,
            DriverLeave.end_date >= check_date
        ).first()

        return leave

    @staticmethod
    def get_driver_leaves(driver_id, include_deleted=False):
        """
        Get all leaves for a specific driver.

        Args:
            driver_id: ID of the driver
            include_deleted: Whether to include soft-deleted records

        Returns:
            list: List of DriverLeave objects
        """
        if include_deleted:
            query = DriverLeave.query_all()
        else:
            query = DriverLeave.query_active()

        leaves = query.filter_by(driver_id=driver_id).order_by(
            DriverLeave.start_date.desc()
        ).all()

        return leaves

    @staticmethod
    def get_all_leaves(status=None, active_only=True, start_date=None, end_date=None):
        """
        Get all driver leaves with optional filtering.

        Args:
            status: Filter by status (approved, pending, rejected, cancelled)
            active_only: Whether to show only active (future/current) leaves
            start_date: Filter leaves starting on or after this date (string or date object)
            end_date: Filter leaves ending on or before this date (string or date object)

        Returns:
            list: List of DriverLeave objects
        """
        query = DriverLeave.query_active()

        if status:
            query = query.filter_by(status=status)

        if active_only:
            today = datetime.now(timezone.utc).date()
            query = query.filter(DriverLeave.end_date >= today)

        if start_date:
            # Convert to date object if string
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(DriverLeave.start_date >= start_date)

        if end_date:
            # Convert to date object if string
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(DriverLeave.end_date <= end_date)

        leaves = query.order_by(DriverLeave.start_date.desc()).all()

        return leaves

    @staticmethod
    def update_leave(leave_id, **kwargs):
        """
        Update an existing leave record.

        Args:
            leave_id: ID of the leave to update
            **kwargs: Fields to update

        Returns:
            DriverLeave: Updated leave object

        Raises:
            ServiceError: If validation fails or trying to approve with affected jobs
        """
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            raise ServiceError(f"Leave with ID {leave_id} not found")

        # Convert date strings to date objects
        if 'start_date' in kwargs and kwargs['start_date'] is not None:
            if isinstance(kwargs['start_date'], str):
                kwargs['start_date'] = datetime.strptime(kwargs['start_date'], '%Y-%m-%d').date()

        if 'end_date' in kwargs and kwargs['end_date'] is not None:
            if isinstance(kwargs['end_date'], str):
                kwargs['end_date'] = datetime.strptime(kwargs['end_date'], '%Y-%m-%d').date()

        # Validate dates are not in the past
        today = datetime.now(timezone.utc).date()

        # Get the effective dates (updated or existing)
        effective_start = kwargs.get('start_date', leave.start_date)
        effective_end = kwargs.get('end_date', leave.end_date)

        # Check if start date is in the past
        if effective_start < today:
            raise ServiceError(f"Cannot update leave: start date ({effective_start}) is in the past")

        # Check if end date is in the past
        if effective_end < today:
            raise ServiceError(f"Cannot update leave: end date ({effective_end}) is in the past")

        # Check date order
        if effective_end < effective_start:
            raise ServiceError("End date cannot be before start date")

        # Sanitize reason field
        if 'reason' in kwargs:
            kwargs['reason'] = sanitize_string(kwargs['reason'], max_length=512, field_name="reason")

        # Check if status is being changed to 'approved'
        if kwargs.get('status') == LeaveStatus.APPROVED:
            # Get current or updated date range
            start_date = kwargs.get('start_date', leave.start_date)
            end_date = kwargs.get('end_date', leave.end_date)

            # Check for affected jobs
            affected_jobs = DriverLeaveService.get_affected_jobs(
                leave.driver_id,
                start_date,
                end_date
            )

            if affected_jobs:
                raise ServiceError(
                    f"Cannot approve leave: {len(affected_jobs)} job(s) still assigned to driver. "
                    f"Please reassign all affected jobs before approval."
                )

        # Update allowed fields
        allowed_fields = ['leave_type', 'start_date', 'end_date', 'status', 'reason']
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                setattr(leave, field, value)

        leave.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(f"Updated leave ID {leave_id}")

        return leave

    @staticmethod
    def delete_leave(leave_id):
        """
        Soft delete a leave record.

        Args:
            leave_id: ID of the leave to delete

        Returns:
            bool: True if successful

        Raises:
            ServiceError: If leave not found
        """
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            raise ServiceError(f"Leave with ID {leave_id} not found")

        leave.is_deleted = True
        leave.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        logger.info(f"Deleted leave ID {leave_id}")

        return True
