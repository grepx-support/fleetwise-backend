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
            return Customer.query.all()
        except Exception as e:
            logging.error(f"Error fetching customers: {e}", exc_info=True)
            raise ServiceError("Could not fetch customers. Please try again later.")

    @staticmethod
    def get_by_id(customer_id):
        try:
            return Customer.query.get(customer_id)
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
            customer = Customer.query.get(customer_id)
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
            customer = Customer.query.get(customer_id)
            if not customer:
                return False
            
            # Check if customer has any jobs
            jobs_count = Job.query.filter_by(customer_id=customer_id).count()
            if jobs_count > 0 and not force_cascade:
                raise ServiceError(f"Cannot delete customer. Customer has {jobs_count} associated job(s). Please delete or reassign the jobs first, or use force_cascade=True to delete all associated records.")
            
            # If force_cascade is True, delete associated records first
            if force_cascade:
                # Delete associated jobs
                if jobs_count > 0:
                    Job.query.filter_by(customer_id=customer_id).delete()
                    logging.info(f"Cascade deleted {jobs_count} jobs for customer {customer_id}")
                
                # Delete associated customer service pricing records
                pricing_count = CustomerServicePricing.query.filter_by(cust_id=customer_id).count()
                if pricing_count > 0:
                    CustomerServicePricing.query.filter_by(cust_id=customer_id).delete()
                    logging.info(f"Cascade deleted {pricing_count} customer service pricing records for customer {customer_id}")
            
            db.session.delete(customer)
            db.session.commit()
            return True
        except ServiceError:
            db.session.rollback()
            raise  # Re-raise ServiceError as-is
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting customer: {e}", exc_info=True)
            raise ServiceError("Could not delete customer. Please try again later.") 