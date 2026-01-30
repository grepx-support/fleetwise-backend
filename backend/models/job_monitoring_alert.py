from backend.extensions import db
from datetime import datetime, timezone
import pytz
from sqlalchemy import and_, or_
from backend.models.job import Job
from backend.models.driver import Driver


class JobMonitoringAlert(db.Model):
    __tablename__ = 'job_monitoring_alert'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id', ondelete='CASCADE'), nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id', ondelete='SET NULL'), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default='active', index=True)  # 'active', 'acknowledged', 'cleared'
    reminder_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    cleared_at = db.Column(db.DateTime, nullable=True)
    last_reminder_at = db.Column(db.DateTime, nullable=True)  # Track when last reminder was sent (added via migration)
    
    # Relationships
    job = db.relationship('Job', backref='monitoring_alerts')
    driver = db.relationship('Driver', backref='monitoring_alerts')

    @classmethod
    def create_or_update_alert(cls, job_id, driver_id):
        """Create a new alert or update existing alert for a job"""
        from sqlalchemy.exc import IntegrityError
        
        try:
            # Use database-level locking to prevent race conditions
            existing_alert = cls.query.filter_by(
                job_id=job_id,
                status='active'
            ).with_for_update().first()
            
            if existing_alert:
                # Update reminder count only - don't modify created_at to preserve semantic meaning
                existing_alert.reminder_count += 1
                # Update the last reminder timestamp
                existing_alert.last_reminder_at = datetime.now(timezone.utc)
                db.session.commit()
                return existing_alert
            else:
                # Create new alert
                alert = cls(
                    job_id=job_id,
                    driver_id=driver_id,
                    status='active',
                    created_at=datetime.now(timezone.utc)
                )
                db.session.add(alert)
                db.session.commit()
                return alert
                
        except IntegrityError as e:
            # Handle case where another process created the alert between our check and insert
            db.session.rollback()
            # Try to get the existing alert that was just created
            existing_alert = cls.query.filter_by(
                job_id=job_id,
                status='active'
            ).first()
            if existing_alert:
                # Update the existing alert - don't modify created_at to preserve semantic meaning
                existing_alert.reminder_count += 1
                # Update the last reminder timestamp
                existing_alert.last_reminder_at = datetime.now(timezone.utc)
                db.session.commit()
                return existing_alert
            else:
                # If still no alert found, re-raise the exception
                raise
    
    @classmethod
    def get_active_alerts(cls):
        """Get all active alerts for the admin dashboard"""
        from sqlalchemy import desc
        
        # Get alerts that are still active and not older than 24 hours
        # We keep dismissed alerts for 24 hours as per requirement
        cutoff_time = datetime.now(timezone.utc)
        alerts = cls.query.filter(
            or_(
                cls.status == 'active',
                and_(
                    cls.status == 'acknowledged',
                    cls.acknowledged_at >= cutoff_time
                )
            )
        ).order_by(desc(cls.created_at)).all()
        
        # Preload all jobs and drivers referenced by the alerts to avoid N+1 queries
        job_ids = {alert.job_id for alert in alerts if alert.job_id}
        jobs_by_id = {}
        drivers_by_id = {}
        
        if job_ids:
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            jobs_by_id = {job.id: job for job in jobs}
            
            # Get driver IDs for the jobs
            driver_ids = {job.driver_id for job in jobs if job.driver_id}
            if driver_ids:
                drivers = Driver.query.filter(Driver.id.in_(driver_ids)).all()
                drivers_by_id = {driver.id: driver for driver in drivers}
        
        # Enhance with job and driver details
        result = []
        for alert in alerts:
            job = jobs_by_id.get(alert.job_id)
            if job:
                driver = drivers_by_id.get(job.driver_id) if job.driver_id else None
                
                # Calculate elapsed time since pickup_time
                from dateutil.parser import parse
                
                pickup_datetime = None
                if job.pickup_date and job.pickup_time:
                    pickup_str = f"{job.pickup_date} {job.pickup_time}"
                    try:
                        # Parse the pickup datetime string
                        pickup_datetime = parse(pickup_str)
                        # Since the job pickup_date and pickup_time are stored as strings
                        # representing local time in Singapore, we need to properly handle timezone conversion
                        if pickup_datetime.tzinfo is None:
                            # Assume it's in Singapore timezone
                            sg_tz = pytz.timezone('Asia/Singapore')
                            pickup_datetime = sg_tz.localize(pickup_datetime)
                        # Convert to UTC for comparison
                        pickup_datetime = pickup_datetime.astimezone(pytz.UTC)
                    except:
                        # If parsing fails, skip elapsed time calculation
                        pickup_datetime = None
                
                elapsed_minutes = None
                if pickup_datetime:
                    elapsed_seconds = (datetime.now(timezone.utc) - pickup_datetime).total_seconds()
                    elapsed_minutes = int(elapsed_seconds / 60)
                
                # Convert UTC timestamps to Singapore timezone for consistent display
                singapore_tz = pytz.timezone('Asia/Singapore')
                created_at_sgt = alert.created_at.astimezone(singapore_tz)
                
                # Also convert acknowledged_at, cleared_at, and last_reminder_at if they exist
                acknowledged_at_sgt = alert.acknowledged_at.astimezone(singapore_tz) if alert.acknowledged_at else None
                cleared_at_sgt = alert.cleared_at.astimezone(singapore_tz) if alert.cleared_at else None
                last_reminder_at_sgt = alert.last_reminder_at.astimezone(singapore_tz) if alert.last_reminder_at else None
                
                result.append({
                    'id': alert.id,
                    'job_id': job.id,
                    'driver_name': driver.name if driver else 'Unassigned',
                    'driver_mobile': driver.mobile if driver else None,
                    'passenger_name': job.passenger_name,
                    'passenger_mobile': job.passenger_mobile,
                    'pickup_time': job.pickup_time,
                    'pickup_date': job.pickup_date,
                    'status': alert.status,
                    'reminder_count': alert.reminder_count,
                    'created_at': created_at_sgt.isoformat(),
                    'acknowledged_at': acknowledged_at_sgt.isoformat() if acknowledged_at_sgt else None,
                    'cleared_at': cleared_at_sgt.isoformat() if cleared_at_sgt else None,
                    'last_reminder_at': last_reminder_at_sgt.isoformat() if last_reminder_at_sgt else None,
                    'elapsed_minutes': elapsed_minutes,
                    'service_type': job.service_type,
                    'pickup_location': job.pickup_location,
                    'dropoff_location': job.dropoff_location
                })
        
        return result
    
    @classmethod
    def acknowledge_alert(cls, alert_id):
        """Mark an alert as acknowledged"""
        alert = cls.query.get(alert_id)
        if alert and alert.status == 'active':
            alert.status = 'acknowledged'
            alert.acknowledged_at = datetime.now(timezone.utc)
            db.session.commit()
            return True
        return False
    
    @classmethod
    def clear_alert(cls, job_id):
        """Clear all alerts for a job when status changes to OTW or job is canceled"""
        alerts = cls.query.filter_by(job_id=job_id).all()
        for alert in alerts:
            alert.status = 'cleared'
            alert.cleared_at = datetime.now(timezone.utc)
        db.session.commit()
    
    @classmethod
    def clear_alerts_for_canceled_jobs(cls, job_ids):
        """Clear all alerts for multiple jobs that have been canceled"""
        if not job_ids:
            return
        alerts = cls.query.filter(cls.job_id.in_(job_ids)).all()
        for alert in alerts:
            alert.status = 'cleared'
            alert.cleared_at = datetime.now(timezone.utc)
        db.session.commit()
    
    @classmethod
    def find_overdue_jobs(cls, threshold_minutes=None):
        """Find jobs that are confirmed but haven't started within threshold minutes of pickup time"""
        from sqlalchemy import and_
        import pytz
        from datetime import timedelta
        from dateutil.parser import parse
        import logging
        
        current_time = datetime.now(timezone.utc)
        logging.info(f"Job monitoring check at {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')} (UTC), threshold: {threshold_minutes} minutes")
        
        # Find confirmed jobs where pickup_time + threshold_minutes < current_time
        overdue_jobs = []
        jobs = Job.query.filter(
            Job.status == 'confirmed',
            Job.is_deleted.is_(False),
            Job.pickup_date.isnot(None),
            Job.pickup_time.isnot(None)
        ).all()
        
        logging.info(f"Found {len(jobs)} confirmed jobs to check for overdue status")
        
        # Log job details for debugging
        for job in jobs:
            logging.info(f"Job {job.id}: status='{job.status}', pickup_date='{job.pickup_date}', pickup_time='{job.pickup_time}', is_deleted={job.is_deleted}")
        
        for job in jobs:
            try:
                # Construct full pickup datetime
                pickup_str = f"{job.pickup_date} {job.pickup_time}"
                pickup_datetime = parse(pickup_str)
                # If the parsed datetime doesn't have timezone info, assume it's local time
                if pickup_datetime.tzinfo is None:
                    # Use Singapore timezone (as per application configuration)
                    sg_tz = pytz.timezone('Asia/Singapore')
                    pickup_datetime = sg_tz.localize(pickup_datetime, is_dst=None)
                    # Convert to UTC for comparison
                    pickup_datetime = pickup_datetime.astimezone(timezone.utc)
                else:
                    # If timezone info exists, convert to UTC for comparison
                    pickup_datetime = pickup_datetime.astimezone(timezone.utc)
                
                # Calculate the deadline: pickup time - threshold minutes (subtract threshold from pickup time for pre-alert detection)
                deadline = pickup_datetime - timedelta(minutes=threshold_minutes)
                
                # Calculate elapsed time for logging (convert both to UTC for accurate calculation)
                current_time_utc = datetime.now(timezone.utc)
                elapsed_since_pickup = (current_time_utc - pickup_datetime).total_seconds() / 60
                
                logging.info(f"Job {job.id}: pickup {pickup_datetime}, threshold {threshold_minutes}, deadline {deadline}, current {current_time_utc}, elapsed {elapsed_since_pickup:.1f} min")
                
                # Check if the pre-alert condition is met (all in same timezone)
                if deadline <= current_time_utc < pickup_datetime:
                    logging.info(f"Job {job.id} pre-alert condition met - deadline {deadline} <= current {current_time_utc} < pickup {pickup_datetime}")
                    overdue_jobs.append(job)
                else:
                    logging.info(f"Job {job.id} pre-alert condition not met - deadline {deadline} > current {current_time_utc} or current {current_time_utc} >= pickup {pickup_datetime}")
            except Exception as e:
                # If parsing fails, skip this job and log detailed error
                logging.error(f"Failed to parse datetime for job {job.id}: date='{job.pickup_date}', time='{job.pickup_time}', error: {str(e)}")
                logging.error(f"Full job data: id={job.id}, status='{job.status}', is_deleted={job.is_deleted}")
                continue
        
        logging.info(f"Total overdue jobs found: {len(overdue_jobs)}")
        return overdue_jobs