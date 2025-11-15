import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Any, Optional, Union
from backend.extensions import db
from backend.models.driver_leave import DriverLeave
from backend.models.job_reassignment import JobReassignment
from backend.models.job import Job
from backend.models.driver import Driver
from backend.models.vehicle import Vehicle
from backend.models.contractor import Contractor
from backend.services.job_service import JobService
from flask_security import current_user

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


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

        # Validate leave type
        allowed_types = ['sick_leave', 'vacation', 'personal', 'emergency']
        if leave_type not in allowed_types:
            raise ServiceError(f"Invalid leave type. Must be one of: {', '.join(allowed_types)}")

        # Validate status
        allowed_statuses = ['approved', 'pending', 'rejected', 'cancelled']
        if status not in allowed_statuses:
            raise ServiceError(f"Invalid status. Must be one of: {', '.join(allowed_statuses)}")

        # Check for overlapping leaves with row-level locking (prevents race conditions)
        overlapping_leaves = DriverLeave.query_active().filter(
            DriverLeave.driver_id == driver_id,
            DriverLeave.status.in_(['approved', 'pending']),
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

        # Create leave record with date objects
        leave = DriverLeave(
            driver_id=driver_id,
            leave_type=leave_type,
            start_date=start_dt,  # Use date object
            end_date=end_dt,      # Use date object
            status=status,
            reason=reason,
            created_by=created_by,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
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

        # Note: Job.pickup_date might be stored as string, need to handle both
        affected_jobs = Job.query_active().filter(
            Job.driver_id == driver_id,
            Job.pickup_date >= start_dt.strftime('%Y-%m-%d'),  # Convert to string for comparison
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
                - job_id: ID of the job to reassign
                - reassignment_type: 'driver', 'vehicle', or 'contractor'
                - new_driver_id: (optional) New driver ID
                - new_vehicle_id: (optional) New vehicle ID
                - new_contractor_id: (optional) New contractor ID
                - notes: (optional) Reassignment notes
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

                    reassignment_type = reassignment_data.get('reassignment_type')

                    # Perform reassignment based on type
                    if reassignment_type == 'driver':
                        DriverLeaveService._reassign_to_driver(
                            job,
                            reassignment_data.get('new_driver_id'),
                            reassignment_data.get('new_vehicle_id'),
                            leave.start_date,
                            leave.end_date
                        )
                    elif reassignment_type == 'vehicle':
                        DriverLeaveService._reassign_to_vehicle(
                            job,
                            reassignment_data.get('new_vehicle_id')
                        )
                    elif reassignment_type == 'contractor':
                        DriverLeaveService._reassign_to_contractor(
                            job,
                            reassignment_data.get('new_contractor_id')
                        )
                    else:
                        raise ServiceError(f"Invalid reassignment type: {reassignment_type}")

                    # Create reassignment audit record
                    reassignment = JobReassignment(
                        job_id=job_id,
                        driver_leave_id=leave_id,
                        original_driver_id=original_driver_id,
                        original_vehicle_id=original_vehicle_id,
                        original_contractor_id=original_contractor_id,
                        reassignment_type=reassignment_type,
                        new_driver_id=job.driver_id,
                        new_vehicle_id=job.vehicle_id,
                        new_contractor_id=job.contractor_id,
                        notes=reassignment_data.get('notes'),
                        reassigned_by=reassigned_by,
                        reassigned_at=datetime.utcnow()
                    )

                    db.session.add(reassignment)

                    results['success'].append({
                        'job_id': job_id,
                        'reassignment_type': reassignment_type,
                        'message': f"Job {job_id} successfully reassigned"
                    })

                    logger.info(f"Job {job_id} reassigned: {reassignment_type}")

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
    def _reassign_to_driver(job, new_driver_id, new_vehicle_id=None, leave_start_date=None, leave_end_date=None):
        """Reassign job to a new driver (with optional vehicle)"""
        if not new_driver_id:
            raise ServiceError("new_driver_id is required for driver reassignment")

        # Validate new driver exists and is active
        new_driver = Driver.query_active().filter_by(id=new_driver_id).first()
        if not new_driver:
            raise ServiceError(f"Driver {new_driver_id} not found or inactive")

        # Check if new driver is on leave during the job period
        if leave_start_date and leave_end_date:
            conflicting_leave = DriverLeave.query_active().filter(
                DriverLeave.driver_id == new_driver_id,
                DriverLeave.status == 'approved',
                DriverLeave.start_date <= job.pickup_date,
                DriverLeave.end_date >= job.pickup_date
            ).first()

            if conflicting_leave:
                raise ServiceError(
                    f"Driver {new_driver_id} is on leave from {conflicting_leave.start_date} to {conflicting_leave.end_date}"
                )

        # Check for scheduling conflicts
        conflict = JobService.check_driver_conflict(
            new_driver_id,
            job.pickup_date,
            job.pickup_time,
            job_id=job.id
        )
        if conflict:
            raise ServiceError(
                f"Driver {new_driver_id} has a conflicting job at {job.pickup_date} {job.pickup_time}"
            )

        # If vehicle not specified, use driver's assigned vehicle
        if not new_vehicle_id:
            new_vehicle_id = new_driver.vehicle_id

        # Validate vehicle
        if new_vehicle_id:
            vehicle = Vehicle.query_active().filter_by(id=new_vehicle_id).first()
            if not vehicle:
                raise ServiceError(f"Vehicle {new_vehicle_id} not found or inactive")

        # Update job
        job.driver_id = new_driver_id
        job.vehicle_id = new_vehicle_id
        job.contractor_id = None  # Clear contractor if switching to driver
        job.updated_at = datetime.utcnow()

    @staticmethod
    def _reassign_to_vehicle(job, new_vehicle_id):
        """Reassign job to a different vehicle (same driver)"""
        if not new_vehicle_id:
            raise ServiceError("new_vehicle_id is required for vehicle reassignment")

        # Validate vehicle exists and is active
        vehicle = Vehicle.query_active().filter_by(id=new_vehicle_id).first()
        if not vehicle:
            raise ServiceError(f"Vehicle {new_vehicle_id} not found or inactive")

        # Update job
        job.vehicle_id = new_vehicle_id
        job.updated_at = datetime.utcnow()

    @staticmethod
    def _reassign_to_contractor(job, new_contractor_id):
        """Reassign job to a contractor"""
        if not new_contractor_id:
            raise ServiceError("new_contractor_id is required for contractor reassignment")

        # Validate contractor exists and is active
        contractor = Contractor.query_active().filter_by(id=new_contractor_id).first()
        if not contractor:
            raise ServiceError(f"Contractor {new_contractor_id} not found or inactive")

        # Update job
        job.contractor_id = new_contractor_id
        job.driver_id = None  # Clear driver when assigning to contractor
        job.vehicle_id = None  # Clear vehicle when assigning to contractor
        job.updated_at = datetime.utcnow()

    @staticmethod
    def check_driver_on_leave(driver_id, date_str):
        """
        Check if a driver is on approved leave on a specific date.

        Args:
            driver_id: ID of the driver
            date_str: Date to check in YYYY-MM-DD format

        Returns:
            DriverLeave object if driver is on leave, None otherwise
        """
        leave = DriverLeave.query_active().filter(
            DriverLeave.driver_id == driver_id,
            DriverLeave.status == 'approved',
            DriverLeave.start_date <= date_str,
            DriverLeave.end_date >= date_str
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
            start_date: Filter leaves starting on or after this date
            end_date: Filter leaves ending on or before this date

        Returns:
            list: List of DriverLeave objects
        """
        query = DriverLeave.query_active()

        if status:
            query = query.filter_by(status=status)

        if active_only:
            today = datetime.now().strftime('%Y-%m-%d')
            query = query.filter(DriverLeave.end_date >= today)

        if start_date:
            query = query.filter(DriverLeave.start_date >= start_date)

        if end_date:
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
            ServiceError: If validation fails
        """
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            raise ServiceError(f"Leave with ID {leave_id} not found")

        # Update allowed fields
        allowed_fields = ['leave_type', 'start_date', 'end_date', 'status', 'reason']
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                setattr(leave, field, value)

        leave.updated_at = datetime.utcnow()
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
        leave.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"Deleted leave ID {leave_id}")

        return True
