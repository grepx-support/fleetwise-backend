from backend.extensions import db
from datetime import datetime
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    cleared_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    job = db.relationship('Job', backref='monitoring_alerts')
    driver = db.relationship('Driver', backref='monitoring_alerts')

    @classmethod
    def create_or_update_alert(cls, job_id, driver_id):
        """Create a new alert or update existing alert for a job"""
        # Check if an active alert already exists for this job
        existing_alert = cls.query.filter_by(
            job_id=job_id,
            status='active'
        ).first()
        
        if existing_alert:
            # Update reminder count
            existing_alert.reminder_count += 1
            existing_alert.created_at = datetime.utcnow()
            db.session.commit()
            return existing_alert
        else:
            # Create new alert
            alert = cls(
                job_id=job_id,
                driver_id=driver_id,
                status='active'
            )
            db.session.add(alert)
            db.session.commit()
            return alert
    
    @classmethod
    def get_active_alerts(cls):
        """Get all active alerts for the admin dashboard"""
        from sqlalchemy import desc
        
        # Get alerts that are still active and not older than 24 hours
        # We keep dismissed alerts for 24 hours as per requirement
        cutoff_time = datetime.utcnow()
        alerts = cls.query.filter(
            or_(
                cls.status == 'active',
                and_(
                    cls.status == 'acknowledged',
                    cls.acknowledged_at >= cutoff_time
                )
            )
        ).order_by(desc(cls.created_at)).all()
        
        # Enhance with job and driver details
        result = []
        for alert in alerts:
            job = Job.query.get(alert.job_id)
            if job:
                driver = Driver.query.get(job.driver_id) if job.driver_id else None
                
                # Calculate elapsed time since pickup_time
                import pytz
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
                    elapsed_seconds = (datetime.now(pytz.UTC) - pickup_datetime).total_seconds()
                    elapsed_minutes = int(elapsed_seconds / 60)
                
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
                    'created_at': alert.created_at.isoformat(),
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
            alert.acknowledged_at = datetime.utcnow()
            db.session.commit()
            return True
        return False
    
    @classmethod
    def clear_alert(cls, job_id):
        """Clear all alerts for a job when status changes to OTW or job is canceled"""
        alerts = cls.query.filter_by(job_id=job_id).all()
        for alert in alerts:
            alert.status = 'cleared'
            alert.cleared_at = datetime.utcnow()
        db.session.commit()
    
    @classmethod
    def clear_alerts_for_canceled_jobs(cls, job_ids):
        """Clear all alerts for multiple jobs that have been canceled"""
        if not job_ids:
            return
        alerts = cls.query.filter(cls.job_id.in_(job_ids)).all()
        for alert in alerts:
            alert.status = 'cleared'
            alert.cleared_at = datetime.utcnow()
        db.session.commit()
    
    @classmethod
    def find_overdue_jobs(cls, threshold_minutes=15):
        """Find jobs that are confirmed but haven't started within threshold minutes of pickup time"""
        from sqlalchemy import and_
        import pytz
        from datetime import timedelta
        from dateutil.parser import parse
        
        cutoff_time = datetime.now(pytz.UTC) - timedelta(minutes=threshold_minutes)
        
        # Find confirmed jobs where pickup_time + threshold_minutes < current_time
        overdue_jobs = []
        jobs = Job.query.filter(
            Job.status == 'confirmed',
            Job.is_deleted.is_(False),
            Job.pickup_date.isnot(None),
            Job.pickup_time.isnot(None)
        ).all()
        
        for job in jobs:
            try:
                # Construct full pickup datetime
                pickup_str = f"{job.pickup_date} {job.pickup_time}"
                pickup_datetime = parse(pickup_str)
                # Convert to UTC for comparison
                pickup_datetime = pickup_datetime.replace(tzinfo=pytz.UTC)
                
                # Check if pickup time + 15 minutes is before current time
                if pickup_datetime <= cutoff_time:
                    overdue_jobs.append(job)
            except:
                # If parsing fails, skip this job
                continue
        
        return overdue_jobs