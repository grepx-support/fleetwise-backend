import logging
from backend.extensions import db
from backend.models.bill import Bill
from backend.models.job import Job
from backend.models.contractor import Contractor
from decimal import Decimal

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class BillService:
    @staticmethod
    def get_all():
        try:
            return Bill.query.all()
        except Exception as e:
            logging.error(f"Error fetching bills: {e}", exc_info=True)
            raise ServiceError("Could not fetch bills. Please try again later.")

    @staticmethod
    def get_by_id(bill_id):
        try:
            return Bill.query.get(bill_id)
        except Exception as e:
            logging.error(f"Error fetching bill: {e}", exc_info=True)
            raise ServiceError("Could not fetch bill. Please try again later.")

    @staticmethod
    def create(data):
        try:
            bill = Bill(**data)
            db.session.add(bill)
            db.session.commit()
            return bill
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating bill: {e}", exc_info=True)
            raise ServiceError("Could not create bill. Please try again later.")

    @staticmethod
    def update(bill_id, data):
        try:
            bill = Bill.query.get(bill_id)
            if not bill:
                return None
            for key, value in data.items():
                setattr(bill, key, value)
            db.session.commit()
            return bill
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating bill: {e}", exc_info=True)
            raise ServiceError("Could not update bill. Please try again later.")

    @staticmethod
    def delete(bill_id):
        try:
            bill = Bill.query.get(bill_id)
            if not bill:
                return False
            
            # Allow deletion of bills with 'Generated' status
            # Also allow deletion of contractor bills (which have contractor_id) regardless of status
            # And allow deletion of driver bills with 'Proceed' or 'Processed' status
            if bill.status != 'Generated':
                # If it's a contractor bill (has contractor_id), allow deletion regardless of status
                if bill.contractor_id is not None:
                    # Allow deletion for contractor bills regardless of status
                    pass
                # If it's a driver bill (no contractor_id) and status is 'Proceed' or 'Processed', allow deletion
                elif bill.contractor_id is None and (bill.status == 'Proceed' or bill.status == 'Processed'):
                    # Allow deletion for driver bills with 'Proceed' or 'Processed' status
                    pass
                else:
                    raise ServiceError(f'Cannot delete bill with status: {bill.status}')
            
            # Delete the bill (cascade will delete bill items)
            db.session.delete(bill)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting bill: {e}", exc_info=True)
            raise ServiceError("Could not delete bill. Please try again later.")

    @staticmethod
    def get_billable_jobs(contractor_id=None):
        """
        Get jobs that are completed (status='jc') or stand down (status='sd') and not yet billed to a contractor.
        Excludes jobs assigned to internal contractors (those with '(Internal)' in their name).
        """
        try:
            # Get all jobs with jc or sd status and contractor
            base_query = Job.query.filter(
                Job.status.in_(['jc', 'sd']),
                Job.contractor_id.isnot(None),
                Job.bill_id.is_(None)  # Not yet billed
            )
            
            # Exclude jobs assigned to internal contractors
            base_query = base_query.join(Contractor).filter(
                ~Contractor.name.contains('(Internal)')
            )
            
            if contractor_id:
                base_query = base_query.filter(Job.contractor_id == contractor_id)
                
            result = base_query.all()
            
            return result
        except Exception as e:
            logging.error(f"Error fetching billable jobs: {e}", exc_info=True)
            raise ServiceError("Could not fetch billable jobs. Please try again later.")

    @staticmethod
    def generate_contractor_bill(contractor_id, job_ids):
        """
        Generate a single bill for all jobs selected.
        All jobs will be associated with the same bill ID if they belong to the same contractor.
        """
        try:
            # Validate contractor exists
            contractor = Contractor.query.get(contractor_id)
            if not contractor:
                raise ServiceError(f"Contractor with id {contractor_id} does not exist.")
            
            # Validate jobs
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            if len(jobs) != len(job_ids):
                found_ids = [job.id for job in jobs]
                missing_ids = list(set(job_ids) - set(found_ids))
                raise ServiceError(f"Jobs with ids {missing_ids} do not exist.")
            
            # Check that all jobs belong to the specified contractor
            for job in jobs:
                if job.contractor_id != contractor_id:
                    raise ServiceError(f"Job {job.id} does not belong to contractor {contractor_id}.")
                
                # Check that job is completed (only 'jc' or 'sd' status jobs can be billed)
                if job.status not in ['jc', 'sd']:
                    raise ServiceError(f"Job {job.id} is not completed or stand down (status: {job.status}). Jobs must be completed (jc) or stand down (sd) to be billed.")
                
                # Check that job is not already billed (commented out since you don't want to use BillItem)
                # if job.bill_items and len(job.bill_items) > 0:
                #     raise ServiceError(f"Job {job.id} is already billed.")
            
            # Create a single bill for all jobs
            bill = Bill(
                contractor_id=contractor_id,
                total_amount=Decimal('0.00'),
                status='Generated',  # All bills are 'Generated'
            )
            db.session.add(bill)
            db.session.flush()  # Get bill ID
            
            # Associate all jobs with the bill and calculate total amount
            total_amount = Decimal('0.00')
            for job in jobs:
                # Associate the job with the bill
                job.bill_id = bill.id
                
                # Calculate amount for this job (job_cost - cash collected)
                # Convert to Decimal to ensure proper arithmetic operations
                job_cost = Decimal(str(job.job_cost or 0.0))
                cash_collected = Decimal(str(job.cash_to_collect or 0.0))
                job_amount = job_cost - cash_collected
                total_amount += job_amount
            
            # Update bill total amount
            bill.total_amount = total_amount
            
            db.session.commit()
            
            # Return the bill created
            return [bill]
        except ServiceError:
            # Re-raise ServiceError as-is
            raise
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error generating contractor bill: {e}", exc_info=True)
            raise ServiceError(f"Could not generate contractor bill: {str(e)}")

    @staticmethod
    def get_driver_billable_jobs(driver_id=None):
        """
        Get jobs that are completed (status='jc') or stand down (status='sd') and not yet billed to a driver.
        Only includes jobs assigned to internal contractors (those with '(Internal)' in their name).
        """
        try:
            # Get all jobs with jc or sd status and driver
            base_query = Job.query.filter(
                Job.status.in_(['jc', 'sd']),
                Job.driver_id.isnot(None),
                Job.contractor_id.isnot(None),  # Must have a contractor assigned
                Job.bill_id.is_(None)  # Not yet billed
            )
            
            # Only include jobs assigned to internal contractors
            base_query = base_query.join(Contractor).filter(
                Contractor.name.contains('(Internal)')
            )
            
            if driver_id:
                base_query = base_query.filter(Job.driver_id == driver_id)
                
            result = base_query.all()
            
            return result
        except Exception as e:
            logging.error(f"Error fetching driver billable jobs: {e}", exc_info=True)
            raise ServiceError("Could not fetch driver billable jobs. Please try again later.")

    @staticmethod
    def generate_driver_bill(driver_id, job_ids):
        """
        Generate a single bill for all jobs selected.
        All jobs will be associated with the same bill ID if they belong to the same driver.
        """
        try:
            # Validate driver exists
            from backend.models.driver import Driver
            driver = Driver.query.get(driver_id)
            if not driver:
                raise ServiceError(f"Driver with id {driver_id} does not exist.")
            
            # Validate jobs
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            if len(jobs) != len(job_ids):
                found_ids = [job.id for job in jobs]
                missing_ids = list(set(job_ids) - set(found_ids))
                raise ServiceError(f"Jobs with ids {missing_ids} do not exist.")
            
            # Check that all jobs belong to the specified driver
            for job in jobs:
                if job.driver_id != driver_id:
                    raise ServiceError(f"Job {job.id} does not belong to driver {driver_id}.")
                
                # Check that job is completed (only 'jc' or 'sd' status jobs can be billed)
                if job.status not in ['jc', 'sd']:
                    raise ServiceError(f"Job {job.id} is not completed or stand down (status: {job.status}). Jobs must be completed (jc) or stand down (sd) to be billed.")
                
                # Check that job is not already billed (commented out since you don't want to use BillItem)
                # if job.bill_items and len(job.bill_items) > 0:
                #     raise ServiceError(f"Job {job.id} is already billed.")
            
            # Create a single bill for all jobs
            bill = Bill(
                contractor_id=None,  # Explicitly set to None for driver bills
                driver_id=driver_id,  # Set the driver_id for driver bills
                total_amount=Decimal('0.00'),
                status='Generated'
            )
            db.session.add(bill)
            db.session.flush()  # Get bill ID
            
            # Associate all jobs with the bill and calculate total amount
            total_amount = Decimal('0.00')
            for job in jobs:
                # Associate the job with the bill
                job.bill_id = bill.id
                
                # Calculate amount for this job (commission - cash collected)
                # Convert to Decimal to ensure proper arithmetic operations
                commission = Decimal(str(job.driver_commission or 0.0))
                cash_collected = Decimal(str(job.cash_to_collect or 0.0))
                job_amount = commission - cash_collected
                total_amount += job_amount
            
            # Update bill total amount
            bill.total_amount = total_amount
            
            db.session.commit()
            
            # Return the bill created
            return [bill]
        except ServiceError:
            # Re-raise ServiceError as-is
            raise
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error generating driver bills: {e}", exc_info=True)
            raise ServiceError(f"Could not generate driver bills: {str(e)}")