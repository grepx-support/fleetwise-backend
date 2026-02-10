import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from flask import current_app
from backend.models.password_reset_token import PasswordResetToken
from backend.models.job_monitoring_alert import JobMonitoringAlert
from backend.models.job import Job
from backend.extensions import db

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for scheduled background tasks with enhanced monitoring and resource management"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.job_stats = {}
        self.setup_event_listeners()
        self.setup_jobs()
        
    def setup_event_listeners(self):
        """Setup event listeners for job monitoring."""
        def job_executed(event):
            job_id = event.job_id
            if job_id not in self.job_stats:
                self.job_stats[job_id] = {'executions': 0, 'errors': 0, 'last_run': None}
            
            self.job_stats[job_id]['executions'] += 1
            self.job_stats[job_id]['last_run'] = datetime.now()
            logger.info(f"Job {job_id} executed successfully")
            
        def job_error(event):
            job_id = event.job_id
            if job_id not in self.job_stats:
                self.job_stats[job_id] = {'executions': 0, 'errors': 0, 'last_run': None}
            
            self.job_stats[job_id]['errors'] += 1
            self.job_stats[job_id]['last_run'] = datetime.now()
            logger.error(f"Job {job_id} failed: {event.exception}")
            
        def job_missed(event):
            job_id = event.job_id
            logger.warning(f"Job {job_id} was missed at {event.scheduled_run_time}")
            
        self.scheduler.add_listener(job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(job_error, EVENT_JOB_ERROR)
        self.scheduler.add_listener(job_missed, EVENT_JOB_MISSED)

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
        """Clean up expired and used password reset tokens with timeout protection"""
        start_time = time.time()
        timeout_seconds = 60  # 1 minute timeout
        
        try:
            from flask import current_app
            with current_app.app_context():
                # Check for timeout
                if time.time() - start_time > timeout_seconds:
                    logger.warning("Token cleanup timed out during app context setup")
                    return
                
                count = PasswordResetToken.cleanup_expired_tokens()
                db.session.commit()
                logger.info(f"Token cleanup completed: {count} tokens removed")
        except Exception as e:
            logger.error(f"Token cleanup failed: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception as rollback_error:
                logger.error(f"Token cleanup rollback failed: {rollback_error}", exc_info=True)

    def monitor_overdue_jobs(self):
        """Monitor jobs that haven't started within the configured threshold minutes of pickup time with timeout protection"""
        logger.info("=== Starting job monitoring cycle ===")
        start_time = time.time()
        timeout_seconds = 300  # 5 minute timeout
        
        try:
            # Import the app instance directly from the module
            from backend.server import app
            with app.app_context():
                # Check for timeout
                if time.time() - start_time > timeout_seconds:
                    logger.warning("Job monitoring timed out during app context setup")
                    return
                
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
                
                for i, job in enumerate(overdue_jobs):
                    # Check for timeout periodically
                    if time.time() - start_time > timeout_seconds:
                        logger.warning(f"Job monitoring timed out while processing job {i+1}/{len(overdue_jobs)}")
                        break
                    
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
        """Clean up alerts that are older than 24 hours and have been acknowledged/cleared with timeout protection"""
        start_time = time.time()
        timeout_seconds = 120  # 2 minute timeout
        
        try:
            from flask import current_app
            from datetime import datetime, timedelta
            with current_app.app_context():
                # Check for timeout
                if time.time() - start_time > timeout_seconds:
                    logger.warning("Alert cleanup timed out during app context setup")
                    return
                
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
                logger.info(f"Found {count} old alerts to clean up")
                
                # Process alerts with timeout check
                processed_count = 0
                for alert in old_alerts:
                    if time.time() - start_time > timeout_seconds:
                        logger.warning(f"Alert cleanup timed out after processing {processed_count}/{count} alerts")
                        break
                    
                    try:
                        db.session.delete(alert)
                        processed_count += 1
                    except Exception as delete_error:
                        logger.error(f"Failed to delete alert {alert.id}: {delete_error}")
                        continue
                
                db.session.commit()
                logger.info(f"Alert cleanup completed: removed {processed_count} old alerts")
                
        except Exception as e:
            logger.error(f"Alert cleanup failed: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception as rollback_error:
                logger.error(f"Alert cleanup rollback failed: {rollback_error}", exc_info=True)

    def start(self):
        """Start the scheduler with enhanced logging - only in main process"""
        # Only start scheduler in the main Flask process, not in worker processes
        import os
        if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
            logger.info("Scheduler service skipped - not in main process")
            return
            
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler service started successfully in main process")
            jobs = self.scheduler.get_jobs()
            logger.info(f"Scheduler jobs: {[job.id for job in jobs]}")
            logger.info(f"Total jobs scheduled: {len(jobs)}")
        else:
            logger.info("Scheduler service was already running")

    def shutdown(self):
        """Shutdown the scheduler gracefully with cleanup"""
        if self.scheduler.running:
            logger.info("Shutting down scheduler service...")
            # Log final statistics
            self.log_scheduler_stats()
            # Shutdown scheduler
            self.scheduler.shutdown(wait=True)  # Wait for jobs to finish
            logger.info("Scheduler service stopped")
        
    def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics and health information."""
        return {
            'running': self.scheduler.running,
            'job_count': len(self.scheduler.get_jobs()),
            'job_stats': self.job_stats,
            'next_run_times': {
                job.id: job.next_run_time.isoformat() if job.next_run_time else None
                for job in self.scheduler.get_jobs()
            }
        }
        
    def log_scheduler_stats(self):
        """Log detailed scheduler statistics."""
        stats = self.get_stats()
        logger.info(f"Scheduler Stats: {stats}")
        
        # Log individual job performance
        for job_id, job_stat in self.job_stats.items():
            success_rate = (
                job_stat['executions'] / (job_stat['executions'] + job_stat['errors']) * 100
                if (job_stat['executions'] + job_stat['errors']) > 0 else 0
            )
            logger.info(f"Job {job_id}: {job_stat['executions']} executions, "
                       f"{job_stat['errors']} errors, {success_rate:.1f}% success rate")
        
    def pause_job(self, job_id: str) -> bool:
        """Pause a specific job."""
        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"Job {job_id} paused")
            return True
        except Exception as e:
            logger.error(f"Failed to pause job {job_id}: {e}")
            return False
            
    def resume_job(self, job_id: str) -> bool:
        """Resume a specific job."""
        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"Job {job_id} resumed")
            return True
        except Exception as e:
            logger.error(f"Failed to resume job {job_id}: {e}")
            return False
            
    def health_check(self) -> bool:
        """Perform scheduler health check."""
        try:
            return self.scheduler.running and len(self.scheduler.get_jobs()) > 0
        except Exception as e:
            logger.error(f"Scheduler health check failed: {e}")
            return False


scheduler_service = SchedulerService()
