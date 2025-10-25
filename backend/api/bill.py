from flask import Blueprint, request, jsonify
from backend.services.bill_service import BillService, ServiceError
from backend.schemas.bill_schema import BillSchema
import logging
from flask_security import roles_accepted, auth_required
from backend.extensions import db
from backend.models.bill import Bill

bill_bp = Blueprint('bill', __name__)
schema = BillSchema()
schema_many = BillSchema(many=True)

@bill_bp.route('/bills', methods=['GET'])
@roles_accepted('admin')
def list_bills():
    try:
        # Get filter parameters
        bill_type = request.args.get('type')  # 'contractor' or 'driver'
        
        # Start with all bills query
        query = Bill.query
        
        # Apply filters based on type
        if bill_type == 'contractor':
            # Only contractor bills (where contractor_id is not null)
            query = query.filter(Bill.contractor_id.isnot(None))
        elif bill_type == 'driver':
            # Only driver bills (where contractor_id is null)
            query = query.filter(Bill.contractor_id.is_(None))
        
        bills = query.all()
        
        # Load the driver information for driver bills and jobs
        for bill in bills:
            if bill.contractor_id is None:  # Driver bill
                # Access the driver property to load it
                _ = bill.driver
            # Load jobs for all bills by accessing the relationship
            _ = bill.jobs
        
        response_data = {
            'items': schema_many.dump(bills),
            'total': len(bills)
        }
        return jsonify(response_data), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_bills: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@bill_bp.route('/bills/<int:bill_id>', methods=['GET'])
@roles_accepted('admin')
def get_bill(bill_id):
    try:
        bill = BillService.get_by_id(bill_id)
        if not bill:
            return jsonify({'error': 'Bill not found'}), 404
        # Load jobs for this bill
        _ = bill.jobs
        return jsonify(schema.dump(bill)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_bill: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@bill_bp.route('/bills', methods=['POST'])
@roles_accepted('admin')
def create_bill():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        bill = BillService.create(data)
        return jsonify(schema.dump(bill)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_bill: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@bill_bp.route('/bills/<int:bill_id>', methods=['PUT'])
@roles_accepted('admin')
def update_bill(bill_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        bill = BillService.update(bill_id, data)
        if not bill:
            return jsonify({'error': 'Bill not found'}), 404
        return jsonify(schema.dump(bill)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_bill: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@bill_bp.route('/bills/<int:bill_id>', methods=['DELETE'])
@roles_accepted('admin')
def delete_bill(bill_id):
    try:
        success = BillService.delete(bill_id)
        if not success:
            return jsonify({'error': 'Bill not found'}), 404
        return jsonify({'message': 'Bill deleted'}), 200
    except ServiceError as se:
        db.session.rollback()  # Explicit rollback
        return jsonify({'error': se.message}), 400
    except Exception as e:
        db.session.rollback()  # Explicit rollback for any other exception
        logging.error(f"Unhandled error in delete_bill: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@bill_bp.route('/bills/contractor', methods=['POST'])
@roles_accepted('admin')
def generate_contractor_bill():
    try:
        data = request.get_json()
        contractor_id = data.get('contractor_id')
        job_id = data.get('job_id')
        
        # job_id is required
        if not job_id:
            return jsonify({'error': 'job_id is required'}), 400
        
        # Handle both single job_id (int) and multiple job_ids (list)
        if isinstance(job_id, list):
            job_ids = job_id
        else:
            job_ids = [job_id]
        
        # If contractor_id is not provided, determine it from the jobs
        if not contractor_id:
            from backend.models.job import Job
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            
            if len(jobs) != len(job_ids):
                found_ids = [job.id for job in jobs]
                missing_ids = list(set(job_ids) - set(found_ids))
                return jsonify({'error': f'Jobs with ids {missing_ids} do not exist.'}), 400
            
            # Extract contractor IDs from jobs
            contractor_ids = list(set(job.contractor_id for job in jobs if job.contractor_id is not None))
            
            # Check if all jobs have contractors
            if len(contractor_ids) == 0:
                return jsonify({'error': 'Selected jobs must have a contractor assigned'}), 400
            
            # Check if all jobs belong to the same contractor
            if len(contractor_ids) > 1:
                return jsonify({'error': 'All selected jobs must belong to the same contractor'}), 400
                
            contractor_id = contractor_ids[0]
        
        # Validate contractor exists
        from backend.models.contractor import Contractor
        contractor = Contractor.query.get(contractor_id)
        if not contractor:
            return jsonify({'error': f'Contractor with id {contractor_id} does not exist.'}), 400
        
        # Check if there's an existing unpaid bill for this contractor
        from backend.models.bill import Bill
        from backend.models.job import Job
        existing_bill = None
        
        # Find existing unpaid bill for this contractor
        unpaid_bills = Bill.query.filter_by(
            contractor_id=contractor_id,
            status='Unpaid'
        ).all()
        
        # Use the first existing bill if there is one
        if unpaid_bills:
            existing_bill = unpaid_bills[0]
        
        # If there's an existing bill, add jobs to it; otherwise create a new bill
        if existing_bill:
            # Add jobs to existing bill
            from decimal import Decimal
            
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            
            # Validate jobs
            if len(jobs) != len(job_ids):
                found_ids = [job.id for job in jobs]
                missing_ids = list(set(job_ids) - set(found_ids))
                return jsonify({'error': f'Jobs with ids {missing_ids} do not exist.'}), 400
            
            # Check that all jobs belong to the specified contractor
            for job in jobs:
                if job.contractor_id != contractor_id:
                    return jsonify({'error': f'Job {job.id} does not belong to contractor {contractor_id}.'}), 400
                
                # Check that job is completed (only 'jc' or 'sd' status jobs can be billed)
                if job.status not in ['jc', 'sd']:
                    return jsonify({'error': f'Job {job.id} is not completed or stand down (status: {job.status}). Jobs must be completed (jc) or stand down (sd) to be billed.'}), 400
                
                # Check that job is not already billed
                if job.bill_id is not None:
                    return jsonify({'error': f'Job {job.id} is already billed.'}), 400
            
            # Associate all jobs with the existing bill and update total amount
            total_amount = Decimal(str(existing_bill.total_amount or 0.0))
            for job in jobs:
                # Associate the job with the bill
                job.bill_id = existing_bill.id
                
                # Calculate amount for this job (job_cost - cash collected)
                job_cost = Decimal(str(job.job_cost or 0.0))
                cash_collected = Decimal(str(job.cash_to_collect or 0.0))
                job_amount = job_cost - cash_collected
                total_amount += job_amount
            
            # Update bill total amount
            existing_bill.total_amount = total_amount
            
            db.session.commit()
            
            bill_info = [{
                'id': existing_bill.id,
                'status': existing_bill.status,
                'total_amount': float(existing_bill.total_amount) if existing_bill.total_amount else 0.0
            }]
            
            message = f'Successfully added {len(jobs)} job(s) to existing bill #{existing_bill.id} for contractor {contractor_id}'
            
            return jsonify({
                'bills': bill_info,
                'message': message
            }), 201
        else:
            # Generate a new single bill for all jobs
            bills = BillService.generate_contractor_bill(contractor_id, job_ids)
            
            # Return information about all created bills
            bill_info = []
            for bill in bills:
                bill_info.append({
                    'id': bill.id,
                    'status': bill.status,
                    'total_amount': float(bill.total_amount) if bill.total_amount else 0.0
                })
            
            message = f'Successfully created 1 bill for contractor {contractor_id} with {len(job_ids)} job(s). Bill is active (Unpaid).'
            
            return jsonify({
                'bills': bill_info,
                'message': message
            }), 201
    except ServiceError as se:
        db.session.rollback()
        return jsonify({'error': se.message}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"Unhandled error in generate_contractor_bill: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@bill_bp.route('/bills/<int:bill_id>/jobs/<int:job_id>', methods=['DELETE'])
@roles_accepted('admin')
def remove_job_from_bill(bill_id, job_id):
    try:
        # Get the bill
        bill = Bill.query.get(bill_id)
        if not bill:
            return jsonify({'error': 'Bill not found'}), 404
            
        # Prevent modification of non-unpaid bills
        if bill.status != 'Unpaid':
            return jsonify({'error': f'Cannot modify bill with status: {bill.status}'}), 400
            
        # Get the job for this bill
        from backend.models.job import Job
        job = Job.query.filter_by(id=job_id, bill_id=bill_id).first()
        if not job:
            return jsonify({'error': 'Job not found in this bill'}), 404
            
        # Remove the job from the bill
        job.bill_id = None
        
        # Recalculate the bill total
        from backend.models.job import Job
        bill_jobs = Job.query.filter_by(bill_id=bill_id).all()
        total_amount = sum(float(job.job_cost or 0.0) - float(job.cash_to_collect or 0.0) for job in bill_jobs)
        bill.total_amount = total_amount if bill_jobs else 0
        
        # If the bill has no more jobs associated with it, delete the bill automatically
        if not bill_jobs:
            db.session.delete(bill)
            db.session.commit()
            return jsonify({'message': 'Job removed from bill successfully. Bill deleted automatically as it had no more jobs.'}), 200
        
        db.session.commit()
        
        return jsonify({'message': 'Job removed from bill successfully'}), 200
    except Exception as e:
        db.session.rollback()
        logging.error(f"Unhandled error in remove_job_from_bill: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@bill_bp.route('/bills/driver', methods=['POST'])
@roles_accepted('admin')
def generate_driver_bill():
    try:
        data = request.get_json()
        driver_id = data.get('driver_id')
        job_id = data.get('job_id')
        
        # job_id is required
        if not job_id:
            return jsonify({'error': 'job_id is required'}), 400
        
        # Handle both single job_id (int) and multiple job_ids (list)
        if isinstance(job_id, list):
            job_ids = job_id
        else:
            job_ids = [job_id]
        
        # If driver_id is not provided, determine it from the jobs
        if not driver_id:
            from backend.models.job import Job
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            
            if len(jobs) != len(job_ids):
                found_ids = [job.id for job in jobs]
                missing_ids = list(set(job_ids) - set(found_ids))
                return jsonify({'error': f'Jobs with ids {missing_ids} do not exist.'}), 400
            
            # Extract driver IDs from jobs
            driver_ids = list(set(job.driver_id for job in jobs if job.driver_id is not None))
            
            # Check if all jobs have drivers
            if len(driver_ids) == 0:
                return jsonify({'error': 'Selected jobs must have a driver assigned'}), 400
            
            # Check if all jobs belong to the same driver
            if len(driver_ids) > 1:
                return jsonify({'error': 'All selected jobs must belong to the same driver'}), 400
                
            driver_id = driver_ids[0]
        
        # Validate driver exists
        from backend.models.driver import Driver
        driver = Driver.query.get(driver_id)
        if not driver:
            return jsonify({'error': f'Driver with id {driver_id} does not exist.'}), 400
        
        # Check if there's an existing unpaid bill for this driver
        from backend.models.bill import Bill
        from backend.models.job import Job
        existing_bill = None
        
        # Find existing unpaid bill for this driver
        unpaid_bills = Bill.query.filter_by(
            contractor_id=None,
            status='Unpaid'
        ).all()
        
        # Look for a bill that already has jobs for this driver
        for bill in unpaid_bills:
            bill_jobs = Job.query.filter_by(bill_id=bill.id).all()
            if bill_jobs and any(job.driver_id == driver_id for job in bill_jobs):
                existing_bill = bill
                break
        
        # If there's an existing bill, add jobs to it; otherwise create a new bill
        if existing_bill:
            # Add jobs to existing bill
            from decimal import Decimal
            
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            
            # Validate jobs
            if len(jobs) != len(job_ids):
                found_ids = [job.id for job in jobs]
                missing_ids = list(set(job_ids) - set(found_ids))
                return jsonify({'error': f'Jobs with ids {missing_ids} do not exist.'}), 400
            
            # Check that all jobs belong to the specified driver
            for job in jobs:
                if job.driver_id != driver_id:
                    return jsonify({'error': f'Job {job.id} does not belong to driver {driver_id}.'}), 400
                
                # Check that job is completed (only 'jc' or 'sd' status jobs can be billed)
                if job.status not in ['jc', 'sd']:
                    return jsonify({'error': f'Job {job.id} is not completed or stand down (status: {job.status}). Jobs must be completed (jc) or stand down (sd) to be billed.'}), 400
                
                # Check that job is not already billed
                if job.bill_id is not None:
                    return jsonify({'error': f'Job {job.id} is already billed.'}), 400
            
            # Associate all jobs with the existing bill and update total amount
            total_amount = Decimal(str(existing_bill.total_amount or 0.0))
            for job in jobs:
                # Associate the job with the bill
                job.bill_id = existing_bill.id
                
                # Calculate amount for this job (job_cost - cash collected)
                job_cost = Decimal(str(job.job_cost or 0.0))
                cash_collected = Decimal(str(job.cash_to_collect or 0.0))
                job_amount = job_cost - cash_collected
                total_amount += job_amount
            
            # Update bill total amount - allow negative values
            existing_bill.total_amount = total_amount
            
            # Ensure driver_id is set on the existing bill
            if existing_bill.driver_id is None:
                existing_bill.driver_id = driver_id
            
            db.session.commit()
            
            bill_info = [{
                'id': existing_bill.id,
                'status': existing_bill.status,
                'total_amount': float(existing_bill.total_amount) if existing_bill.total_amount else 0.0
            }]
            
            message = f'Successfully added {len(jobs)} job(s) to existing bill #{existing_bill.id} for driver {driver_id}'
            
            return jsonify({
                'bills': bill_info,
                'message': message
            }), 201
        else:
            # Generate a new single bill for all jobs
            bills = BillService.generate_driver_bill(driver_id, job_ids)
            
            # Return information about the created bill
            bill_info = []
            for bill in bills:
                bill_info.append({
                    'id': bill.id,
                    'status': bill.status,
                    'total_amount': float(bill.total_amount) if bill.total_amount else 0.0
                })
            
            message = f'Successfully created 1 bill for driver {driver_id} with {len(job_ids)} job(s). Bill is active (Unpaid).'
            
            return jsonify({
                'bills': bill_info,
                'message': message
            }), 201
    except ServiceError as se:
        db.session.rollback()
        return jsonify({'error': se.message}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"Unhandled error in generate_driver_bill: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
