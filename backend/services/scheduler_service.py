import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.models.password_reset_token import PasswordResetToken
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
