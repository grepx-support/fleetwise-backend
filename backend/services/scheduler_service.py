import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.models.password_reset_token import PasswordResetToken
from backend.models.job_monitoring_alert import JobMonitoringAlert
from backend.extensions import db

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for scheduled background tasks"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.setup_jobs()

    def setup_jobs(self):
        """Configure all scheduled jobs"""
        # Run token cleanup daily at 2:00 AM
        self.scheduler.add_job(
            func=self.cleanup_expired_tokens,
            trigger=CronTrigger(hour=2, minute=0),
            id='cleanup_expired_tokens',
            name='Clean up expired password reset tokens',
            replace_existing=True
        )
        logger.info("Scheduled job: Token cleanup at 2:00 AM daily")
        
        # Run job monitoring with interval from system settings
        trigger_interval = self._get_trigger_interval()
        self.scheduler.add_job(
            func=self.monitor_overdue_jobs,
            trigger="interval",
            minutes=trigger_interval,
            id='monitor_overdue_jobs',
            name='Monitor jobs that are overdue to start',
            replace_existing=True
        )
        logger.info(f"Scheduled job: Job monitoring every {trigger_interval} minutes (from system settings)")
        
        # Run alert cleanup daily at 3:00 AM (clear alerts older than 24 hours)
        self.scheduler.add_job(
            func=self.cleanup_old_alerts,
            trigger=CronTrigger(hour=3, minute=0),
            id='cleanup_old_alerts',
            name='Clean up old job monitoring alerts',
            replace_existing=True
        )
        logger.info("Scheduled job: Alert cleanup at 3:00 AM daily")

    def _get_trigger_interval(self):
        """Get the trigger interval from settings, with fallback to default"""
        logger.info("Attempting to load trigger interval from system settings...")
        try:
            # Import the app instance directly from the module
            from backend.server import app
            with app.app_context():
                logger.info("App context acquired, attempting to load monitoring settings...")
                from backend.api.job_monitoring import get_monitoring_settings_from_db
                settings = get_monitoring_settings_from_db()
                logger.info(f"Raw settings from DB: {settings}")
                interval = settings.get('trigger_frequency_minutes', 10)
                logger.info(f"Extracted trigger interval: {interval} minutes")
                logger.info(f"Full settings loaded: {settings}")
                return interval
        except Exception as e:
            logger.warning(f"Could not load monitoring settings, using default interval (10 min): {e}")
            logger.exception("Exception details:")
            return 10

    def update_monitoring_schedule(self):
        """Update the monitoring job schedule based on current settings"""
        try:
            from flask import current_app
            with current_app.app_context():
                new_interval = self._get_trigger_interval()
                
                # Get the current job
                job = self.scheduler.get_job('monitor_overdue_jobs')
                if job:
                    # Get current interval in minutes (convert from seconds)
                    current_minutes = int(job.trigger.interval.total_seconds() / 60)
                    
                    # Check if the interval has changed
                    if current_minutes != new_interval:
                        # Reschedule the job with the new interval
                        self.scheduler.reschedule_job(
                            'monitor_overdue_jobs',
                            trigger='interval',
                            minutes=new_interval
                        )
                        logger.info(f"Rescheduled monitoring job to run every {new_interval} minutes (was {current_minutes})")
                    else:
                        logger.debug(f"Monitoring job schedule unchanged: still {new_interval} minutes")
                else:
                    logger.warning("Could not find monitoring job to reschedule")
        except Exception as e:
            logger.error(f"Error updating monitoring schedule: {e}", exc_info=True)

    def cleanup_expired_tokens(self):
        """Clean up expired and used password reset tokens"""
        try:
            from flask import current_app
            with current_app.app_context():
                count = PasswordResetToken.cleanup_expired_tokens()
                db.session.commit()
                logger.info(f"Token cleanup completed: {count} tokens removed")
        except Exception as e:
            logger.error(f"Token cleanup failed: {e}", exc_info=True)
            db.session.rollback()

    def monitor_overdue_jobs(self):
        """Monitor jobs that haven't started within the configured threshold minutes of pickup time"""
        logger.info("=== Starting job monitoring cycle ===")
        try:
            # Import the app instance directly from the module
            from backend.server import app
            with app.app_context():
                # Get custom monitoring settings
                from backend.api.job_monitoring import get_monitoring_settings_from_db
                settings = get_monitoring_settings_from_db()
                threshold_minutes = settings.get('pickup_threshold_minutes', 15)
                
                logger.info(f"Using pickup threshold: {threshold_minutes} minutes")
                logger.info(f"Full settings: {settings}")
                
                # Check if we need to reschedule ourselves based on the trigger frequency setting
                desired_interval = settings.get('trigger_frequency_minutes', 10)
                current_job = self.scheduler.get_job('monitor_overdue_jobs')
                
                if current_job:
                    # Get current interval in minutes
                    current_interval = int(current_job.trigger.interval.total_seconds() / 60)
                    if current_interval != desired_interval:
                        logger.info(f"Rescheduling monitoring job from {current_interval} to {desired_interval} minutes")
                        self.scheduler.reschedule_job(
                            'monitor_overdue_jobs',
                            trigger='interval',
                            minutes=desired_interval
                        )
                
                # Find jobs that are overdue (confirmed but not started within threshold minutes of pickup time)
                overdue_jobs = JobMonitoringAlert.find_overdue_jobs(threshold_minutes=threshold_minutes)
                
                # Get reminder settings
                max_reminders = settings.get('max_alert_reminders', 2)
                reminder_interval = settings.get('reminder_interval_minutes', 10)
                
                logger.info(f"Using max reminders: {max_reminders}, reminder interval: {reminder_interval} minutes")
                logger.info(f"Scheduler trigger frequency: {settings.get('trigger_frequency_minutes', 10)} minutes")
                
                logger.info(f"Found {len(overdue_jobs)} overdue jobs to process")
                
                for job in overdue_jobs:
                    # Check if there's already an active alert for this job
                    existing_alert = JobMonitoringAlert.query.filter_by(
                        job_id=job.id,
                        status='active'
                    ).first()
                    
                    if existing_alert:
                        # Check if we should send another reminder (based on custom interval and max reminders)
                        if existing_alert.reminder_count < max_reminders:
                            # Check if enough time has passed since the last reminder
                            from datetime import datetime
                            import pytz
                            # Use last_reminder_at if available, otherwise fall back to created_at for backward compatibility
                            last_reminder_time = existing_alert.last_reminder_at or existing_alert.created_at
                            # Ensure both times are in the same timezone for comparison
                            singapore_tz = pytz.timezone('Asia/Singapore')
                            current_time_sgt = datetime.now(singapore_tz)
                            # Convert last_reminder_time to Singapore timezone if it's naive
                            if last_reminder_time.tzinfo is None:
                                last_reminder_time_sg = singapore_tz.localize(last_reminder_time)
                            else:
                                last_reminder_time_sg = last_reminder_time.astimezone(singapore_tz)
                            time_since_last_reminder = (current_time_sgt - last_reminder_time_sg).total_seconds() / 60
                            
                            if time_since_last_reminder >= reminder_interval:
                                # Update the alert to increment reminder count
                                JobMonitoringAlert.create_or_update_alert(job.id, job.driver_id)
                                logger.info(f"Sent reminder #{existing_alert.reminder_count + 1} for job {job.id} (elapsed: {time_since_last_reminder:.1f} minutes)")
                            else:
                                logger.info(f"Skipping reminder for job {job.id} - only {time_since_last_reminder:.1f} minutes elapsed, need {reminder_interval} minutes")
                        else:
                            logger.info(f"Max reminders reached for job {job.id}, skipping")
                    else:
                        # Create a new alert
                        JobMonitoringAlert.create_or_update_alert(job.id, job.driver_id)
                        logger.info(f"Created monitoring alert for overdue job {job.id}")
                
                db.session.commit()
                logger.info(f"Job monitoring completed: checked {len(overdue_jobs)} jobs")
                logger.info("=== Job monitoring cycle completed ===")
        except Exception as e:
            logger.error(f"Job monitoring failed: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception as rollback_error:
                logger.error(f"Job monitoring rollback failed: {rollback_error}", exc_info=True)

    def cleanup_old_alerts(self):
        """Clean up alerts that are older than 24 hours and have been acknowledged/cleared"""
        try:
            from flask import current_app
            from datetime import datetime, timedelta
            with current_app.app_context():
                import pytz
                singapore_tz = pytz.timezone('Asia/Singapore')
                current_time_sgt = datetime.now(singapore_tz)
                cutoff_time = current_time_sgt - timedelta(hours=24)
                
                # Find alerts that are older than 24 hours and have been acknowledged or cleared
                from sqlalchemy import and_, or_
                old_alerts = JobMonitoringAlert.query.filter(
                    or_(
                        and_(
                            JobMonitoringAlert.status == 'acknowledged',
                            JobMonitoringAlert.acknowledged_at.isnot(None),
                            JobMonitoringAlert.acknowledged_at < cutoff_time,
                        ),
                        and_(
                            JobMonitoringAlert.status == 'cleared',
                            JobMonitoringAlert.cleared_at.isnot(None),
                            JobMonitoringAlert.cleared_at < cutoff_time,
                        ),
                    )
                ).all()
                
                count = len(old_alerts)
                for alert in old_alerts:
                    db.session.delete(alert)
                
                db.session.commit()
                logger.info(f"Alert cleanup completed: removed {count} old alerts")
        except Exception as e:
            logger.error(f"Alert cleanup failed: {e}", exc_info=True)
            db.session.rollback()

    def start(self):
        """Start the scheduler"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler service started successfully")
            logger.info(f"Scheduler jobs: {[job.id for job in self.scheduler.get_jobs()]}")
        else:
            logger.info("Scheduler service was already running")

    def shutdown(self):
        """Shutdown the scheduler gracefully"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler service stopped")


scheduler_service = SchedulerService()
