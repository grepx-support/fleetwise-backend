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
        
        # Run job monitoring every 10 minutes to check for overdue jobs
        self.scheduler.add_job(
            func=self.monitor_overdue_jobs,
            trigger="interval",
            minutes=10,
            id='monitor_overdue_jobs',
            name='Monitor jobs that are overdue to start',
            replace_existing=True
        )
        logger.info("Scheduled job: Job monitoring every 10 minutes")
        
        # Run alert cleanup daily at 3:00 AM (clear alerts older than 24 hours)
        self.scheduler.add_job(
            func=self.cleanup_old_alerts,
            trigger=CronTrigger(hour=3, minute=0),
            id='cleanup_old_alerts',
            name='Clean up old job monitoring alerts',
            replace_existing=True
        )
        logger.info("Scheduled job: Alert cleanup at 3:00 AM daily")

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
        """Monitor jobs that haven't started within 15 minutes of pickup time"""
        try:
            from flask import current_app
            with current_app.app_context():
                # Find jobs that are overdue (confirmed but not started within 15 minutes of pickup time)
                overdue_jobs = JobMonitoringAlert.find_overdue_jobs(threshold_minutes=15)
                
                for job in overdue_jobs:
                    # Check if there's already an active alert for this job
                    existing_alert = JobMonitoringAlert.query.filter_by(
                        job_id=job.id,
                        status='active'
                    ).first()
                    
                    if existing_alert:
                        # Check if we should send another reminder (every 10 mins, max 3 reminders)
                        if existing_alert.reminder_count < 3:
                            # Update the alert to increment reminder count
                            JobMonitoringAlert.create_or_update_alert(job.id, job.driver_id)
                            logger.info(f"Sent reminder #{existing_alert.reminder_count + 1} for job {job.id}")
                        else:
                            logger.info(f"Max reminders reached for job {job.id}, skipping")
                    else:
                        # Create a new alert
                        JobMonitoringAlert.create_or_update_alert(job.id, job.driver_id)
                        logger.info(f"Created monitoring alert for overdue job {job.id}")
                
                db.session.commit()
                logger.info(f"Job monitoring completed: checked {len(overdue_jobs)} jobs")
        except Exception as e:
            logger.error(f"Job monitoring failed: {e}", exc_info=True)
            db.session.rollback()

    def cleanup_old_alerts(self):
        """Clean up alerts that are older than 24 hours and have been acknowledged/cleared"""
        try:
            from flask import current_app
            from datetime import datetime, timedelta
            with current_app.app_context():
                cutoff_time = datetime.utcnow() - timedelta(hours=24)
                
                # Find alerts that are older than 24 hours and have been acknowledged or cleared
                from sqlalchemy import and_
                old_alerts = JobMonitoringAlert.query.filter(
                    JobMonitoringAlert.status.in_(['acknowledged', 'cleared']),
                    and_(
                        JobMonitoringAlert.acknowledged_at.isnot(None),
                        JobMonitoringAlert.acknowledged_at < cutoff_time
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
            logger.info("Scheduler service started")

    def shutdown(self):
        """Shutdown the scheduler gracefully"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler service stopped")


scheduler_service = SchedulerService()
