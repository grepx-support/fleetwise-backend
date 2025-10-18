import logging
from backend.extensions import db
from backend.models.customer import Customer
from backend.models.sub_customer import SubCustomer
from backend.models.job import Job
from backend.models.invoice import Invoice

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class CustomerService:
    @staticmethod
    def get_all():
        try:
            return Customer.query_active().all()
        except Exception as e:
            logging.error(f"Error fetching customers: {e}", exc_info=True)
            raise ServiceError("Could not fetch customers. Please try again later.")

    @staticmethod
    def get_by_id(customer_id):
        try:
            return Customer.query_active().filter_by(id=customer_id).first()
        except Exception as e:
            logging.error(f"Error fetching customer: {e}", exc_info=True)
            raise ServiceError("Could not fetch customer. Please try again later.")

    @staticmethod
    def create(data):
        try:
            customer = Customer(**data)
            db.session.add(customer)
            db.session.commit()
            return customer
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating customer: {e}", exc_info=True)
            raise ServiceError("Could not create customer. Please try again later.")

    @staticmethod
    def update(customer_id, data):
        try:
            customer = Customer.query_active().filter_by(id=customer_id).first()
            if not customer:
                return None
            for key, value in data.items():
                setattr(customer, key, value)
            db.session.commit()
            return customer
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating customer: {e}", exc_info=True)
            raise ServiceError("Could not update customer. Please try again later.")

    @staticmethod
    def delete(customer_id, force_cascade=False):
        from backend.models.job import Job
        from backend.models.customer_service_pricing import CustomerServicePricing
        try:
            customer = Customer.query_active().filter_by(id=customer_id).first()
            if not customer:
                return False
            
            # Check if customer has any jobs
            jobs_count = Job.query_active().filter_by(customer_id=customer_id).count()
            if jobs_count > 0 and not force_cascade:
                raise ServiceError(f"Cannot delete customer. Customer has {jobs_count} associated job(s). Please delete or reassign the jobs first, or use force_cascade=True to delete all associated records.")
            
            # If force_cascade is True, soft delete associated records first
            if force_cascade:
                # Soft delete associated jobs
                if jobs_count > 0:
                    jobs = Job.query_active().filter_by(customer_id=customer_id).all()
                    for job in jobs:
                        job.is_deleted = True
                    logging.info(f"Cascade soft deleted {jobs_count} jobs for customer {customer_id}")
                
                # Note: CustomerServicePricing doesn't have is_deleted column, so we leave it as is
                
            # Soft delete the customer instead of hard delete
            customer.is_deleted = True
            db.session.commit()
            return True
        except ServiceError:
            db.session.rollback()
            raise  # Re-raise ServiceError as-is
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting customer: {e}", exc_info=True)
            raise ServiceError("Could not delete customer. Please try again later.")

    @staticmethod
    def toggle_soft_delete(customer_id, is_deleted):
        try:
            # Get customer including deleted ones for restore functionality
            customer = Customer.query_all().filter_by(id=customer_id).first()
            if not customer:
                return None
            
            customer.is_deleted = is_deleted
            db.session.commit()
            return customer
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error toggling customer soft delete status: {e}", exc_info=True)
            raise ServiceError("Could not update customer status. Please try again later.")
