from flask import Blueprint, request, jsonify
from flask_security.decorators import roles_accepted
from backend.extensions import db
from backend.models.job_monitoring_alert import JobMonitoringAlert
from backend.models.job import Job, JobStatus
from backend.models.driver import Driver
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