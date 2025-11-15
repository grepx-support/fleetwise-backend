from flask import Blueprint, request, jsonify
from backend.services.driver_leave_service import DriverLeaveService, ServiceError
from backend.schemas.driver_leave_schema import (
    DriverLeaveSchema,
    JobReassignmentSchema,
    DriverLeaveCreateResponseSchema,
    JobReassignmentRequestSchema
)
from backend.schemas.job_schema import JobSchema
import logging
from flask_security import roles_required, roles_accepted, auth_required, current_user
from backend.extensions import db

driver_leave_bp = Blueprint('driver_leave', __name__)

# Initialize schemas
leave_schema = DriverLeaveSchema(session=db.session)
leave_schema_many = DriverLeaveSchema(many=True, session=db.session)
leave_create_response_schema = DriverLeaveCreateResponseSchema(session=db.session)
reassignment_schema = JobReassignmentSchema(session=db.session)
reassignment_schema_many = JobReassignmentSchema(many=True, session=db.session)
reassignment_request_schema = JobReassignmentRequestSchema()
job_schema_many = JobSchema(many=True, session=db.session)

logger = logging.getLogger(__name__)


@driver_leave_bp.route('/driver-leaves', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def list_driver_leaves():
    """
    Get all driver leaves with optional filtering.
    Query params:
        - driver_id: Filter by specific driver
        - status: Filter by status (approved, pending, rejected, cancelled)
        - active_only: Show only active/upcoming leaves (default: true)
        - start_date: Filter leaves starting on or after this date
        - end_date: Filter leaves ending on or before this date
    """
    try:
        driver_id = request.args.get('driver_id', type=int)
        status = request.args.get('status')
        active_only = request.args.get('active_only', 'true').lower() == 'true'
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        if driver_id:
            leaves = DriverLeaveService.get_driver_leaves(driver_id)
        else:
            leaves = DriverLeaveService.get_all_leaves(
                status=status,
                active_only=active_only,
                start_date=start_date,
                end_date=end_date
            )

        return jsonify(leave_schema_many.dump(leaves)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logger.error(f"Error listing driver leaves: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@driver_leave_bp.route('/driver-leaves/<int:leave_id>', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def get_driver_leave(leave_id):
    """Get a specific driver leave by ID"""
    try:
        from backend.models.driver_leave import DriverLeave
        leave = DriverLeave.query_active().filter_by(id=leave_id).first()

        if not leave:
            return jsonify({'error': 'Driver leave not found'}), 404

        return jsonify(leave_schema.dump(leave)), 200
    except Exception as e:
        logger.error(f"Error getting driver leave: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@driver_leave_bp.route('/driver-leaves', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_driver_leave():
    """
    Create a new driver leave record.
    Request body:
        - driver_id: ID of the driver (required)
        - leave_type: Type of leave (sick_leave, vacation, personal, emergency) (required)
        - start_date: Start date in YYYY-MM-DD format (required)
        - end_date: End date in YYYY-MM-DD format (required)
        - reason: Reason for leave (optional)
        - status: Leave status (default: approved)
    """
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['driver_id', 'leave_type', 'start_date', 'end_date']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Get current user ID
        created_by = current_user.id if hasattr(current_user, 'id') else None

        # Create leave
        result = DriverLeaveService.create_leave(
            driver_id=data['driver_id'],
            leave_type=data['leave_type'],
            start_date=data['start_date'],
            end_date=data['end_date'],
            reason=data.get('reason'),
            status=data.get('status', 'approved'),
            created_by=created_by
        )

        # Prepare response
        leave = result['leave']
        affected_jobs = result['affected_jobs']

        response_data = {
            'leave': leave_schema.dump(leave),
            'affected_jobs': job_schema_many.dump(affected_jobs),
            'affected_jobs_count': result['affected_jobs_count'],
            'requires_reassignment': result['requires_reassignment'],
            'message': 'Leave created successfully'
        }

        if result['requires_reassignment']:
            response_data['warning'] = f"This leave affects {result['affected_jobs_count']} job(s) that require reassignment"

        logger.info(f"Leave created: ID {leave.id} for driver {data['driver_id']}")

        return jsonify(response_data), 201

    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logger.error(f"Error creating driver leave: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@driver_leave_bp.route('/driver-leaves/<int:leave_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_driver_leave(leave_id):
    """
    Update an existing driver leave.
    Request body can include:
        - leave_type
        - start_date
        - end_date
        - status
        - reason
    """
    try:
        data = request.get_json()

        # Update leave
        leave = DriverLeaveService.update_leave(leave_id, **data)

        logger.info(f"Leave updated: ID {leave_id}")

        return jsonify({
            'leave': leave_schema.dump(leave),
            'message': 'Leave updated successfully'
        }), 200

    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logger.error(f"Error updating driver leave: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@driver_leave_bp.route('/driver-leaves/<int:leave_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def delete_driver_leave(leave_id):
    """Soft delete a driver leave record"""
    try:
        DriverLeaveService.delete_leave(leave_id)

        logger.info(f"Leave deleted: ID {leave_id}")

        return jsonify({'message': 'Leave deleted successfully'}), 200

    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logger.error(f"Error deleting driver leave: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@driver_leave_bp.route('/driver-leaves/<int:leave_id>/affected-jobs', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant')
def get_affected_jobs(leave_id):
    """Get all jobs affected by a specific leave"""
    try:
        from backend.models.driver_leave import DriverLeave

        leave = DriverLeave.query_active().filter_by(id=leave_id).first()
        if not leave:
            return jsonify({'error': 'Driver leave not found'}), 404

        affected_jobs = DriverLeaveService.get_affected_jobs(
            leave.driver_id,
            leave.start_date,
            leave.end_date
        )

        return jsonify({
            'leave_id': leave_id,
            'driver_id': leave.driver_id,
            'start_date': leave.start_date,
            'end_date': leave.end_date,
            'affected_jobs': job_schema_many.dump(affected_jobs),
            'count': len(affected_jobs)
        }), 200

    except Exception as e:
        logger.error(f"Error getting affected jobs: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@driver_leave_bp.route('/driver-leaves/<int:leave_id>/reassign-jobs', methods=['POST'])
@roles_accepted('admin', 'manager')
def reassign_jobs(leave_id):
    """
    Reassign jobs for a driver on leave.
    Request body:
        - job_reassignments: List of reassignment objects
            Each object should contain:
                - job_id: ID of the job to reassign (required)
                - reassignment_type: 'driver', 'vehicle', or 'contractor' (required)
                - new_driver_id: New driver ID (for 'driver' type)
                - new_vehicle_id: New vehicle ID (for 'driver' or 'vehicle' type)
                - new_contractor_id: New contractor ID (for 'contractor' type)
                - notes: Optional notes about the reassignment
    """
    try:
        data = request.get_json()

        if 'job_reassignments' not in data:
            return jsonify({'error': 'Missing required field: job_reassignments'}), 400

        reassignments = data['job_reassignments']

        if not isinstance(reassignments, list):
            return jsonify({'error': 'job_reassignments must be a list'}), 400

        # Get current user ID
        reassigned_by = current_user.id if hasattr(current_user, 'id') else None

        # Perform reassignments
        results = DriverLeaveService.reassign_jobs(
            leave_id=leave_id,
            reassignments=reassignments,
            reassigned_by=reassigned_by
        )

        logger.info(f"Jobs reassigned for leave {leave_id}: {results['success']} successful, {len(results['failed'])} failed")

        return jsonify({
            'message': f"Reassignment complete: {len(results['success'])} successful, {len(results['failed'])} failed",
            'success': results['success'],
            'failed': results['failed'],
            'total': results['total']
        }), 200

    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logger.error(f"Error reassigning jobs: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@driver_leave_bp.route('/drivers/<int:driver_id>/leaves', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant', 'driver')
def get_driver_leave_history(driver_id):
    """Get leave history for a specific driver"""
    try:
        # Only allow access if admin/manager/accountant or the driver themselves
        if not (current_user.has_role('admin') or current_user.has_role('manager') or
                current_user.has_role('accountant') or current_user.driver_id == driver_id):
            return jsonify({'error': 'Forbidden'}), 403

        leaves = DriverLeaveService.get_driver_leaves(driver_id)

        return jsonify({
            'driver_id': driver_id,
            'total_leaves': len(leaves),
            'leaves': leave_schema_many.dump(leaves)
        }), 200

    except Exception as e:
        logger.error(f"Error getting driver leave history: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500


@driver_leave_bp.route('/drivers/<int:driver_id>/check-leave', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant', 'driver')
def check_driver_leave_status(driver_id):
    """
    Check if a driver is on leave for a specific date.
    Query params:
        - date: Date to check in YYYY-MM-DD format (required)
    """
    try:
        # Authorization check: only allow access if admin/manager/accountant or the driver themselves
        if not (current_user.has_role('admin') or
                current_user.has_role('manager') or
                current_user.has_role('accountant') or
                (hasattr(current_user, 'driver_id') and current_user.driver_id == driver_id)):
            return jsonify({'error': 'Forbidden. You can only check your own leave status.'}), 403

        date_str = request.args.get('date')

        if not date_str:
            return jsonify({'error': 'Missing required parameter: date'}), 400

        leave = DriverLeaveService.check_driver_on_leave(driver_id, date_str)

        if leave:
            return jsonify({
                'on_leave': True,
                'leave': leave_schema.dump(leave)
            }), 200
        else:
            return jsonify({
                'on_leave': False,
                'leave': None
            }), 200

    except Exception as e:
        logger.error(f"Error checking driver leave status: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
