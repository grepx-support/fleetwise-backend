import logging
from flask import Blueprint, request, jsonify
from flask_security.decorators import roles_accepted, auth_required
from flask_security import current_user
from marshmallow import ValidationError

from backend.extensions import db
from backend.models.leave_override import LeaveOverride
from backend.models.driver_leave import DriverLeave
from backend.services.leave_override_service import LeaveOverrideService, ServiceError
from backend.schemas.leave_override_schema import (
    LeaveOverrideSchema,
    LeaveOverrideCreateSchema,
    LeaveOverrideBulkCreateSchema,
    LeaveOverrideUpdateSchema,
    AvailabilityWindowSchema
)

logger = logging.getLogger(__name__)

leave_override_bp = Blueprint('leave_override', __name__)

# Schema instances
override_schema = LeaveOverrideSchema()
override_many_schema = LeaveOverrideSchema(many=True)
create_schema = LeaveOverrideCreateSchema()
bulk_create_schema = LeaveOverrideBulkCreateSchema()
update_schema = LeaveOverrideUpdateSchema()
availability_schema = AvailabilityWindowSchema(many=True)


@leave_override_bp.route('/driver-leaves/<int:leave_id>/overrides', methods=['GET'])
@auth_required()
@roles_accepted('admin', 'manager', 'accountant')
def get_overrides_for_leave(leave_id):
    """Get all active overrides for a specific leave."""
    try:
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            return jsonify({'error': 'Leave not found'}), 404

        overrides = LeaveOverrideService.get_overrides_for_leave(leave_id)
        return jsonify(override_many_schema.dump(overrides)), 200

    except Exception as e:
        logger.error(f"Error getting overrides for leave {leave_id}: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500


@leave_override_bp.route('/driver-leaves/<int:leave_id>/overrides/<int:override_id>', methods=['GET'])
@auth_required()
@roles_accepted('admin', 'manager', 'accountant')
def get_override(leave_id, override_id):
    """Get a specific override."""
    try:
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            return jsonify({'error': 'Leave not found'}), 404

        override = LeaveOverrideService.get_override(override_id)
        if not override or override.driver_leave_id != leave_id:
            return jsonify({'error': 'Override not found'}), 404

        return jsonify(override_schema.dump(override)), 200

    except Exception as e:
        logger.error(f"Error getting override {override_id}: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500


@leave_override_bp.route('/driver-leaves/<int:leave_id>/overrides', methods=['POST'])
@auth_required()
@roles_accepted('admin', 'manager')
def create_override(leave_id):
    """Create a new leave override for a specific leave."""
    try:
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            return jsonify({'error': 'Leave not found'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        try:
            data = create_schema.load(data)
        except ValidationError as ve:
            return jsonify({'error': 'Validation failed', 'details': ve.messages}), 400

        override = LeaveOverrideService.create_override(
            driver_leave_id=leave_id,
            override_date=data['override_date'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            override_reason=data['override_reason'],
            created_by_id=current_user.id
        )

        return jsonify(override_schema.dump(override)), 201

    except ServiceError as se:
        logger.warning(f"Service error: {se.message}")
        return jsonify({'error': se.message}), 400
    except ValidationError as ve:
        return jsonify({'error': 'Validation failed', 'details': ve.messages}), 400
    except Exception as e:
        logger.error(f"Error creating override: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500


@leave_override_bp.route('/driver-leaves/overrides/bulk', methods=['POST'])
@auth_required()
@roles_accepted('admin', 'manager')
def bulk_create_overrides():
    """Create overrides for multiple leaves (bulk operation)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        try:
            data = bulk_create_schema.load(data)
        except ValidationError as ve:
            return jsonify({'error': 'Validation failed', 'details': ve.messages}), 400

        leave_ids = data['driver_leave_ids']
        if not leave_ids:
            return jsonify({'error': 'No driver_leave_ids provided'}), 400

        result = LeaveOverrideService.bulk_create_overrides(
            driver_leave_ids=leave_ids,
            override_date=data['override_date'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            override_reason=data['override_reason'],
            created_by_id=current_user.id
        )

        return jsonify({
            'success': override_many_schema.dump(result['success']),
            'failed': result['failed'],
            'summary': {
                'total_attempted': len(leave_ids),
                'successful': len(result['success']),
                'failed': len(result['failed'])
            }
        }), 201

    except ServiceError as se:
        logger.warning(f"Service error: {se.message}")
        return jsonify({'error': se.message}), 400
    except ValidationError as ve:
        return jsonify({'error': 'Validation failed', 'details': ve.messages}), 400
    except Exception as e:
        logger.error(f"Error in bulk override creation: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500


@leave_override_bp.route('/driver-leaves/<int:leave_id>/overrides/<int:override_id>/affected-jobs', methods=['GET'])
@auth_required()
@roles_accepted('admin', 'manager')
def get_override_affected_jobs(leave_id, override_id):
    """Get affected jobs for an override without deleting it."""
    try:
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            return jsonify({'error': 'Leave not found'}), 404

        override = LeaveOverrideService.get_override(override_id)
        if not override or override.driver_leave_id != leave_id:
            return jsonify({'error': 'Override not found'}), 404

        affected_jobs = LeaveOverrideService.get_affected_jobs(override)
        affected_jobs_info = [
            {
                'job_id': job.id,
                'customer': job.customer.name if job.customer else 'Unknown',
                'pickup_date': str(job.pickup_date),
                'pickup_time': str(job.pickup_time),
                'status': job.status,
                'service': job.service.name if job.service else 'Unknown'
            }
            for job in affected_jobs
        ]
        return jsonify(affected_jobs_info), 200

    except Exception as e:
        logger.error(f"Error getting affected jobs for override {override_id}: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500


@leave_override_bp.route('/driver-leaves/<int:leave_id>/overrides/<int:override_id>', methods=['DELETE'])
@auth_required()
@roles_accepted('admin', 'manager')
def delete_override(leave_id, override_id):
    """Delete (soft delete) an override, restoring full leave status. Returns affected jobs info."""
    try:
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            return jsonify({'error': 'Leave not found'}), 404

        override = LeaveOverrideService.get_override(override_id)
        if not override or override.driver_leave_id != leave_id:
            return jsonify({'error': 'Override not found'}), 404

        result = LeaveOverrideService.delete_override(override_id)
        if not result['success']:
            return jsonify({'error': 'Override not found'}), 404

        return jsonify({
            'message': 'Override deleted successfully. Leave now shows as full leave period.',
            'override_id': override_id,
            'affected_jobs': result['affected_jobs']
        }), 200

    except ServiceError as se:
        logger.warning(f"Service error: {se.message}")
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logger.error(f"Error deleting override {override_id}: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500


@leave_override_bp.route('/driver-leaves/<int:leave_id>/availability-windows', methods=['GET'])
@auth_required()
@roles_accepted('admin', 'manager', 'accountant')
def get_availability_windows(leave_id):
    """Get all availability windows (overrides) for a leave on a specific date. Query param: date (YYYY-MM-DD)"""
    try:
        date_str = request.args.get('date')
        if not date_str:
            return jsonify({'error': 'date query parameter required (YYYY-MM-DD)'}), 400

        try:
            from datetime import datetime
            override_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            return jsonify({'error': 'Leave not found'}), 404

        windows = LeaveOverrideService.get_availability_windows(leave_id, override_date)

        return jsonify({
            'leave_id': leave_id,
            'date': str(override_date),
            'availability_windows': availability_schema.dump(windows)
        }), 200

    except Exception as e:
        logger.error(f"Error getting availability windows: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500


@leave_override_bp.route('/driver-leaves/<int:leave_id>/check-availability', methods=['POST'])
@auth_required()
@roles_accepted('admin', 'manager', 'accountant')
def check_driver_availability(leave_id):
    """Check if driver is available during a specific datetime. Used for job assignment validation."""
    try:
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            return jsonify({'error': 'Leave not found'}), 404

        data = request.get_json()
        if not data or 'check_datetime' not in data:
            return jsonify({'error': 'check_datetime required in request body'}), 400

        try:
            from datetime import datetime
            check_datetime = datetime.strptime(data['check_datetime'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return jsonify({'error': 'Invalid datetime format. Use YYYY-MM-DD HH:MM:SS'}), 400

        is_available = LeaveOverrideService.is_driver_available_during_override(leave_id, check_datetime)

        return jsonify({
            'leave_id': leave_id,
            'check_datetime': data['check_datetime'],
            'is_available': is_available
        }), 200

    except Exception as e:
        logger.error(f"Error checking driver availability: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500
