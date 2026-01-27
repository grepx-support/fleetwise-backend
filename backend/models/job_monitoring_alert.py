from backend.extensions import db
from datetime import datetime
from sqlalchemy import and_, or_
from backend.models.job import Job
from backend.models.driver import Driver
import pytz


class JobMonitoringAlert(db.Model):
    __tablename__ = 'job_monitoring_alert'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id', ondelete='CASCADE'), nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id', ondelete='SET NULL'), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default='active', index=True)  # 'active', 'acknowledged', 'cleared'
    reminder_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.timezone('Asia/Singapore')).astimezone(pytz.UTC))
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
                import pytz
                # Update the last reminder timestamp with Singapore timezone
                singapore_tz = pytz.timezone('Asia/Singapore')
                existing_alert.last_reminder_at = datetime.now(singapore_tz).astimezone(pytz.UTC)
                db.session.commit()
                return existing_alert
            else:
                # Create new alert
                import pytz
                # Set created_at with Singapore timezone
                singapore_tz = pytz.timezone('Asia/Singapore')
                alert = cls(
                    job_id=job_id,
                    driver_id=driver_id,
                    status='active',
                    created_at=datetime.now(singapore_tz).astimezone(pytz.UTC)
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
                import pytz
                # Update the last reminder timestamp with Singapore timezone
                singapore_tz = pytz.timezone('Asia/Singapore')
                existing_alert.last_reminder_at = datetime.now(singapore_tz).astimezone(pytz.UTC)
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
        import pytz
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time_sgt = datetime.now(singapore_tz)
        cutoff_time = current_time_sgt.astimezone(pytz.UTC)
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
                        pickup_datetime = parse(pickup_str)
                        # Assume pickup time is in local timezone, convert to UTC for comparison
                        pickup_datetime = pickup_datetime.replace(tzinfo=pytz.UTC)
                    except:
                        # If parsing fails, skip elapsed time calculation
                        pickup_datetime = None
                
                elapsed_minutes = None
                if pickup_datetime:
                    # Use consistent timezone for elapsed time calculation
                    current_time_sgt = datetime.now(singapore_tz)
                    current_time_utc = current_time_sgt.astimezone(pytz.UTC)
                    elapsed_seconds = (current_time_utc - pickup_datetime).total_seconds()
                    elapsed_minutes = int(elapsed_seconds / 60)
                
                # Convert UTC timestamps to Singapore timezone for consistent display
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
            import pytz
            # Set acknowledged time with Singapore timezone
            singapore_tz = pytz.timezone('Asia/Singapore')
            alert.acknowledged_at = datetime.now(singapore_tz).astimezone(pytz.UTC)
            db.session.commit()
            return True
        return False
    
    @classmethod
    def clear_alert(cls, job_id):
        """Clear all alerts for a job when status changes to OTW or job is canceled"""
        alerts = cls.query.filter_by(job_id=job_id).all()
        import pytz
        # Set cleared time with Singapore timezone
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time_utc = datetime.now(singapore_tz).astimezone(pytz.UTC)
        for alert in alerts:
            alert.status = 'cleared'
            alert.cleared_at = current_time_utc
        db.session.commit()
    
    @classmethod
    def clear_alerts_for_canceled_jobs(cls, job_ids):
        """Clear all alerts for multiple jobs that have been canceled"""
        if not job_ids:
            return
        alerts = cls.query.filter(cls.job_id.in_(job_ids)).all()
        import pytz
        # Set cleared time with Singapore timezone
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time_utc = datetime.now(singapore_tz).astimezone(pytz.UTC)
        for alert in alerts:
            alert.status = 'cleared'
            alert.cleared_at = current_time_utc
        db.session.commit()
    
    @classmethod
    def find_overdue_jobs(cls, threshold_minutes=None):
        """Find jobs that are confirmed but haven't started within threshold minutes of pickup time"""
        from sqlalchemy import and_
        import pytz
        from datetime import timedelta
        from dateutil.parser import parse
        import logging
            
        # Get threshold from system settings if not provided
        if threshold_minutes is None:
            try:
                from backend.api.job_monitoring import get_monitoring_settings_from_db
                settings = get_monitoring_settings_from_db()
                threshold_minutes = settings.get('pickup_threshold_minutes', 15)
            except Exception as e:
                logging.warning(f"Failed to load threshold from settings, using default 15: {e}")
                threshold_minutes = 15
            
        # Use Singapore timezone consistently for monitoring as per application configuration
        singapore_tz = pytz.timezone('Asia/Singapore')
        current_time = datetime.now(singapore_tz)
        current_time_utc = current_time.astimezone(pytz.UTC)
        logging.info(f"Job monitoring check at {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')} (Singapore time), threshold: {threshold_minutes} minutes")
        
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
                # More robust date/time parsing
                # Handle various date formats
                pickup_date_str = str(job.pickup_date).strip()
                pickup_time_str = str(job.pickup_time).strip()
                
                # Validate and normalize date format (expect YYYY-MM-DD)
                if len(pickup_date_str) == 10 and pickup_date_str[4] == '-' and pickup_date_str[7] == '-':
                    # Already in correct format YYYY-MM-DD
                    formatted_date = pickup_date_str
                else:
                    # Try to parse and reformat
                    try:
                        parsed_date = parse(pickup_date_str)
                        formatted_date = parsed_date.strftime('%Y-%m-%d')
                    except (ValueError, TypeError):
                        logging.error(f"Cannot parse pickup_date '{pickup_date_str}' for job {job.id}")
                        continue
                
                # Validate and normalize time format (expect HH:MM)
                if len(pickup_time_str) >= 5 and ':' in pickup_time_str:
                    # Extract HH:MM portion
                    time_parts = pickup_time_str.split(':')
                    if len(time_parts) >= 2:
                        hour = time_parts[0].zfill(2)  # Pad with leading zero if needed
                        minute = time_parts[1][:2].zfill(2)  # Take first 2 chars and pad
                        formatted_time = f"{hour}:{minute}"
                    else:
                        logging.error(f"Invalid time format '{pickup_time_str}' for job {job.id}")
                        continue
                else:
                    logging.error(f"Invalid time format '{pickup_time_str}' for job {job.id}")
                    continue
                
                # Construct properly formatted datetime string
                pickup_str = f"{formatted_date} {formatted_time}"
                logging.info(f"Parsing datetime for job {job.id}: '{pickup_str}'")
                
                # Parse the properly formatted string
                pickup_datetime = parse(pickup_str)
                
                # If the parsed datetime doesn't have timezone info, assume it's in Singapore timezone
                if pickup_datetime.tzinfo is None:
                    # Use local timezone (assumes the pickup time is in Singapore timezone)
                    local_tz = pytz.timezone('Asia/Singapore')  # Singapore timezone
                    pickup_datetime = local_tz.localize(pickup_datetime)
                    
                    # Handle edge case: if pickup time is genuinely in the past
                    # Only adjust date if pickup time is earlier TODAY and we've already passed it
                    # AND the job should logically be for tomorrow (like overnight jobs)
                    if (pickup_datetime.date() == current_time.date() and 
                        pickup_datetime.time() < current_time.time() and
                        pickup_datetime.hour < 6):  # Only adjust for early morning times
                        # This handles cases like job scheduled for 5AM but it's now 1PM
                        from datetime import timedelta
                        pickup_datetime = pickup_datetime + timedelta(days=1)
                        logging.info(f"Adjusted pickup date forward by 1 day for job {job.id}: {pickup_datetime}")
                else:
                    # If timezone info exists, convert to Singapore timezone for consistency
                    pickup_datetime = pickup_datetime.astimezone(singapore_tz)
                
                # Calculate the deadline: pickup time - threshold minutes (subtract threshold from pickup time for pre-alert detection)
                deadline = pickup_datetime - timedelta(minutes=threshold_minutes)
                
                # Calculate elapsed time for logging (convert both to UTC for accurate calculation)
                pickup_datetime_utc = pickup_datetime.astimezone(pytz.UTC)
                current_time_utc = current_time.astimezone(pytz.UTC)
                elapsed_since_pickup = (current_time_utc - pickup_datetime_utc).total_seconds() / 60
                
                logging.info(f"Job {job.id}: pickup {pickup_datetime}, threshold {threshold_minutes}, deadline {deadline}, current {current_time}, elapsed {elapsed_since_pickup:.1f} min")
                
                # Check if the pre-alert condition is met (all in same timezone)
                if deadline <= current_time < pickup_datetime:
                    logging.info(f"Job {job.id} pre-alert condition met - deadline {deadline} <= current {current_time} < pickup {pickup_datetime}")
                    overdue_jobs.append(job)
                else:
                    logging.info(f"Job {job.id} pre-alert condition not met - deadline {deadline} > current {current_time} or current {current_time} >= pickup {pickup_datetime}")
            except Exception as e:
                # If parsing fails, skip this job and log detailed error
                logging.error(f"Failed to parse datetime for job {job.id}: date='{job.pickup_date}', time='{job.pickup_time}', error: {str(e)}")
                logging.error(f"Full job data: id={job.id}, status='{job.status}', is_deleted={job.is_deleted}")
                continue
        
        logging.info(f"Total overdue jobs found: {len(overdue_jobs)}")
        return overdue_jobs