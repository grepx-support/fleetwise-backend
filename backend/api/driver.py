from flask import Blueprint, request, jsonify
from backend.services.driver_service import DriverService, ServiceError
from backend.schemas.driver_schema import DriverSchema
import logging
from flask_security import roles_required, roles_accepted, auth_required, current_user
from backend.extensions import db
from datetime import datetime, time
driver_bp = Blueprint('driver', __name__)
schema = DriverSchema(session=db.session)
schema_many = DriverSchema(many=True, session=db.session)
from backend.models.job import Job, JobStatus  
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
MAX_RETRIES = 3
RETRY_DELAY = 0.2 
@driver_bp.route('/drivers', methods=['GET'])
@roles_accepted('admin', 'manager')
def list_drivers():
    try:
        drivers = DriverService.get_all()
        return jsonify(schema_many.dump(drivers)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_drivers: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_bp.route('/drivers/<int:driver_id>', methods=['GET'])
@auth_required()
def get_driver(driver_id):
    try:
        driver = DriverService.get_by_id(driver_id)
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        # Only allow access if admin/manager or the driver themselves
        if current_user.has_role('admin') or current_user.has_role('manager') or current_user.id == driver_id:
            return jsonify(schema.dump(driver)), 200
        return jsonify({'error': 'Forbidden'}), 403
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_driver: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_bp.route('/drivers', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_driver():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        driver = DriverService.create(data)
        return jsonify(schema.dump(driver)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_driver: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_bp.route('/drivers/<int:driver_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_driver(driver_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        driver = DriverService.update(driver_id, data)
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        return jsonify(schema.dump(driver)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_driver: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_bp.route('/drivers/<int:driver_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def delete_driver(driver_id):
    try:
        success = DriverService.delete(driver_id)
        if not success:
            return jsonify({'error': 'Driver not found'}), 404
        return jsonify({'message': 'Driver deleted'}), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_driver: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_bp.route('/drivers/<int:driver_id>/soft-delete', methods=['PUT'])
@roles_accepted('admin', 'manager')
def toggle_driver_soft_delete(driver_id):
    try:
        data = request.get_json()
        is_deleted = data.get('is_deleted', True)
        
        driver = DriverService.toggle_soft_delete(driver_id, is_deleted)
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
            
        return jsonify({
            'message': f'Driver {"deleted" if is_deleted else "restored"} successfully',
            'driver': schema.dump(driver)
        }), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in toggle_driver_soft_delete: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_bp.route('/drivers/<int:driver_id>/billing', methods=['GET'])
def driver_billing_report(driver_id):
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        report = DriverService.get_billing_report(driver_id, start_date, end_date)
        return jsonify(report), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in driver_billing_report: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500 
     
@driver_bp.route('/drivers/<int:driver_id>/jobs', methods=['GET'])
@roles_accepted('admin', 'manager','driver')
def get_driver_jobs(driver_id):
    try:
        page = max(1, int(request.args.get('page', 1)))
        page_size = min(max(1, int(request.args.get('pageSize', 10))), 100)
    
        driver = DriverService.get_by_id(driver_id)
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        if current_user.has_role('admin') or current_user.has_role('manager') or current_user.driver_id == driver_id:
            result = DriverService.getDriverJobs(page, page_size, driver_id)
            return jsonify(result), 200
        else:
            return jsonify({'error': 'Forbidden'}), 403
    except ValueError:
        return jsonify({'error': 'Invalid pagination parameters'}), 400
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_driver_jobs: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_bp.route('/drivers/completed-jobs/<int:driver_id>/jobs', methods=['GET'])
@roles_accepted('admin', 'manager','driver')
def get_driver_completed_jobs(driver_id):
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('pageSize', 10))

        driver = DriverService.get_by_id(driver_id)
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404

        result = DriverService.getDriverCompletedJobs(page, page_size, driver_id)
        return jsonify(result), 200

    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_driver_jobs: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@driver_bp.route('/drivers/<int:driver_id>/jobs/<int:job_id>/status', methods=['PUT'])
@roles_accepted('admin', 'manager', 'driver')
def update_driver_job_status(driver_id, job_id):
    if not (
        current_user.has_role('admin') or
        current_user.has_role('manager') or
        current_user.driver_id == driver_id
    ):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json()
    if not data or 'status' not in data:
        return jsonify({'error': 'Missing status'}), 400
    new_status = data['status']
    ALLOWED_STATUS = [
        JobStatus.CONFIRMED.value, JobStatus.OTW.value,
        JobStatus.OTS.value, JobStatus.POB.value,
        JobStatus.JC.value, JobStatus.SD.value,
        JobStatus.CANCELED.value
    ]
    if new_status not in ALLOWED_STATUS:
        return jsonify({'error': 'Invalid status'}), 400

    for attempt in range(MAX_RETRIES):
        try:
            with db.session.begin():
                job = (
                    Job.query
                    .with_for_update()
                    .filter_by(id=job_id, driver_id=driver_id)
                    .first()
                )

                if not job:
                    return jsonify({'error': 'Job not found'}), 404

                if not job.can_transition_to(new_status):
                    return jsonify({'error': 'Invalid status transition'}), 400

                if job.status == new_status:
                    return jsonify({'message': 'Status already set'}), 200

                job.status = new_status
                job.updated_at = datetime.utcnow()
            return jsonify({'message': 'Status updated'}), 200

        except OperationalError as e:
            db.session.rollback()
            if 'database is locked' in str(e).lower():
                logging.warning(f"Database is locked, retrying... (attempt {attempt + 1})")
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            logging.error(f"Unexpected DB error: {e}", exc_info=True)
            return jsonify({'error': 'Database error'}), 500

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating job status: {e}", exc_info=True)
            return jsonify({'error': 'Update failed'}), 500

    return jsonify({'error': 'Database busy. Try again later.'}), 503

@driver_bp.route('/drivers/download/<int:bill_id>', methods=['GET'])
@roles_accepted('admin', 'manager')
def download_driver_invoice(bill_id):
    try:
        response = DriverService.driver_invoice_download(bill_id)
        if not response:
            return jsonify({'error': 'Driver Invoice not found'}), 404
        return response
    except Exception as e:
        logging.error(f"Unhandled error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to generate invoice PDF'}), 500
    
