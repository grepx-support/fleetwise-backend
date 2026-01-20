from flask import Blueprint, request, jsonify
from flask_security.decorators import roles_accepted
from backend.extensions import db
from backend.models.job_monitoring_alert import JobMonitoringAlert
from backend.models.job import Job, JobStatus
from backend.models.driver import Driver
from backend.models.system_settings import SystemSettings
from backend.api.job import auth_required
from datetime import datetime
import logging

job_monitoring_bp = Blueprint('job_monitoring', __name__)

logger = logging.getLogger(__name__)


@job_monitoring_bp.route('/job-monitoring-alerts', methods=['GET'])
@auth_required()
@roles_accepted('admin', 'manager')
def get_job_monitoring_alerts():
    """
    Fetches active monitoring alerts for the admin dashboard.
    Returns job ID, driver name, pickup time, passenger details, elapsed time.
    """
    try:
        alerts = JobMonitoringAlert.get_active_alerts()
        
        # Count active alerts for badge
        active_count = len([alert for alert in alerts if alert['status'] == 'active'])
        
        return jsonify({
            'alerts': alerts,
            'active_count': active_count,
            'total_count': len(alerts)
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching job monitoring alerts: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while fetching alerts'}), 500


@job_monitoring_bp.route('/job-monitoring-alerts/acknowledge', methods=['POST'])
@auth_required()
@roles_accepted('admin', 'manager')
def acknowledge_job_monitoring_alert():
    """
    Dismisses alerts by marking them as acknowledged.
    """
    try:
        data = request.get_json()
        alert_id = data.get('alert_id')
        
        if not alert_id:
            return jsonify({'error': 'Alert ID is required'}), 400
        
        success = JobMonitoringAlert.acknowledge_alert(alert_id)
        
        if success:
            return jsonify({
                'message': 'Alert acknowledged successfully',
                'alert_id': alert_id
            }), 200
        else:
            return jsonify({'error': 'Alert not found or already acknowledged'}), 404
            
    except Exception as e:
        logger.error(f"Error acknowledging job monitoring alert: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while acknowledging alert'}), 500


@job_monitoring_bp.route('/jobs/<int:job_id>/status/otw', methods=['POST'])
@auth_required()
@roles_accepted('admin', 'manager', 'driver')
def update_job_status_otw(job_id):
    """
    Updates job status to 'On The Way' (OTW).
    This endpoint provides a dedicated way to update job status to OTW.
    """
    try:
        # Get the job
        job = Job.query.get(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        # Check if job can transition to OTW
        if not job.can_transition_to(JobStatus.OTW.value):
            return jsonify({
                'error': f'Job cannot transition from {job.status} to {JobStatus.OTW.value}'
            }), 400
        
        # Store old status for audit
        old_status = job.status
        job.status = JobStatus.OTW.value
        job.updated_at = datetime.utcnow()
        
        # Set start_time if not already set
        if job.start_time is None:
            job.start_time = datetime.utcnow()
        
        # Clear any monitoring alerts for this job
        JobMonitoringAlert.clear_alert(job_id)
        
        # Create audit record
        from backend.models.job_audit import JobAudit
        audit = JobAudit(
            job_id=job.id,
            old_status=old_status,
            new_status=JobStatus.OTW.value,
            changed_by=request.user.id if hasattr(request, 'user') and request.user else None
        )
        db.session.add(audit)
        
        db.session.commit()
        
        # Send push notification to driver if available
        try:
            from backend.services.push_notification_service import PushNotificationService
            if job.driver_id:
                driver = Driver.query.get(job.driver_id)
                if driver:
                    from backend.models.user import User
                    user = User.query.filter_by(driver_id=driver.id).first()
                    if user:
                        for token in [user.android_device_token, user.ios_device_token]:
                            if token:
                                PushNotificationService.send(
                                    token=token,
                                    title="Job Status Updated",
                                    body=f"Job #{job.id} status updated to On The Way",
                                    data={"job_id": str(job.id), "status": "otw"}
                                )
        except Exception as e:
            logger.warning(f"Failed to send push notification for job {job.id}: {e}")
        
        return jsonify({
            'message': 'Job status updated to On The Way successfully',
            'job_id': job_id,
            'old_status': old_status,
            'new_status': JobStatus.OTW.value
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating job status to OTW: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while updating job status'}), 500


@job_monitoring_bp.route('/job-monitoring/run-monitoring', methods=['POST'])
@auth_required()
@roles_accepted('admin', 'manager')
def run_job_monitoring_now():
    """Manually trigger job monitoring to check for overdue jobs immediately"""
    try:
        from backend.services.scheduler_service import scheduler_service
        
        logger.info("Manual job monitoring trigger initiated")
        
        # Run the monitoring function directly
        scheduler_service.monitor_overdue_jobs()
        
        return jsonify({
            'message': 'Job monitoring completed successfully',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Manual job monitoring failed: {e}", exc_info=True)
        return jsonify({
            'error': 'Failed to run job monitoring',
            'details': str(e)
        }), 500


@job_monitoring_bp.route('/job-monitoring/monitoring-settings', methods=['GET', 'POST'])
@auth_required()
@roles_accepted('admin', 'manager')
def job_monitoring_settings():
    """
    Manage job monitoring configuration settings.
    GET: Retrieve current settings
    POST: Update settings
    """
    try:
        if request.method == 'GET':
            logger.info("Processing GET request for monitoring settings")
            settings = get_monitoring_settings_from_db()
            logger.info(f"Returning settings: {settings}")
            return jsonify({'settings': settings}), 200
            
        elif request.method == 'POST':
            data = request.get_json()
            # Handle both 'settings' and 'alert_settings' keys for compatibility
            new_settings = data.get('settings', {})
            if not new_settings:  # If 'settings' key doesn't exist, try 'alert_settings'
                new_settings = data.get('alert_settings', {})
            
            logger.info(f"Received settings to save: {new_settings}")
            
            # Validate settings
            errors = validate_monitoring_settings(new_settings)
            if errors:
                return jsonify({
                    'error': 'Invalid settings',
                    'details': errors
                }), 400
            
            # Save settings
            success = save_monitoring_settings_to_db(new_settings)
            if success:
                logger.info(f"Successfully saved settings: {new_settings}")
                # Verify the save by reading back immediately
                verified_settings = get_monitoring_settings_from_db()
                logger.info(f"Verified settings after save: {verified_settings}")
                return jsonify({
                    'message': 'Settings updated successfully',
                    'settings': verified_settings
                }), 200
            else:
                logger.error("Failed to save settings")
                return jsonify({
                    'error': 'Failed to save settings'
                }), 500
                
    except Exception as e:
        logger.error(f"Error handling job monitoring settings: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred'}), 500


def get_monitoring_settings_from_db():
    """Get current job monitoring settings from database or return defaults"""
    try:
        # Create a fresh query to ensure we get the latest data
        settings_record = db.session.query(SystemSettings).filter_by(
            setting_key='job_monitoring_config'
        ).first()
        
        logger.info(f"Database query result: {settings_record}")
        if settings_record:
            logger.info(f"Retrieved setting_value: {settings_record.setting_value}")
            # Return the setting_value if it exists, even if it's an empty dict
            if hasattr(settings_record, 'setting_value') and settings_record.setting_value is not None:
                return settings_record.setting_value
        else:
            logger.info("No settings record found in database")
    except Exception as e:
        logger.error(f"Failed to load settings from DB: {e}")
    
    # Return defaults
    logger.info("Returning default settings")
    return {
        'alert_history_retention_hours': 24,
        'alert_volume': 70,
        'enable_audio_notifications': True,
        'enable_visual_alerts': True,
        'max_alert_reminders': 2,
        'pickup_threshold_minutes': 15,
        'reminder_interval_minutes': 10
    }


def validate_monitoring_settings(settings):
    """Validate job monitoring settings"""
    errors = []
    
    # Validate numeric values
    numeric_fields = {
        'alert_history_retention_hours': (1, 168),  # 1-168 hours (1 week)
        'alert_volume': (0, 100),  # 0-100%
        'max_alert_reminders': (0, 10),  # 0-10 reminders
        'pickup_threshold_minutes': (1, 120),  # 1-120 minutes
        'reminder_interval_minutes': (1, 60)  # 1-60 minutes
    }
    
    for field, (min_val, max_val) in numeric_fields.items():
        if field in settings:
            try:
                value = int(settings[field])
                if not (min_val <= value <= max_val):
                    errors.append(f'{field} must be between {min_val} and {max_val}')
            except (ValueError, TypeError):
                errors.append(f'{field} must be a valid number')
    
    # Validate boolean values
    boolean_fields = ['enable_audio_notifications', 'enable_visual_alerts']
    for field in boolean_fields:
        if field in settings and not isinstance(settings[field], bool):
            errors.append(f'{field} must be true or false')
    
    return errors


def save_monitoring_settings_to_db(settings):
    """Save job monitoring settings to database"""
    try:
        from flask_security import current_user
        
        logger.info(f"Attempting to save settings: {settings}")
        
        # Get existing or create new record
        settings_record = SystemSettings.query.filter_by(
            setting_key='job_monitoring_config'
        ).first()
        
        logger.info(f"Existing record found: {settings_record is not None}")
        
        # Get user ID if available
        user_id = None
        try:
            if current_user and hasattr(current_user, 'id') and current_user.is_authenticated:
                user_id = current_user.id
                logger.info(f"Current user ID: {user_id}")
        except:
            # If there's an issue with current_user, continue without user ID
            logger.warning("Could not get current user ID")
            pass
        
        if not settings_record:
            logger.info("Creating new settings record")
            settings_record = SystemSettings(
                setting_key='job_monitoring_config',
                updated_by=user_id
            )
        else:
            logger.info("Updating existing settings record")
        
        settings_record.setting_value = settings
        settings_record.updated_by = user_id
        
        db.session.add(settings_record)
        db.session.commit()
        
        # Verify the save worked by querying again
        verification_record = SystemSettings.query.filter_by(
            setting_key='job_monitoring_config'
        ).first()
        logger.info(f"Verification after save - Record: {verification_record is not None}, Value: {verification_record.setting_value if verification_record else None}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to save monitoring settings: {e}", exc_info=True)
        db.session.rollback()
        return False