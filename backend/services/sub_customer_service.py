import logging
from backend.extensions import db
from backend.models.sub_customer import SubCustomer
from backend.models.customer import Customer

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class SubCustomerService:
    @staticmethod
    def get_all():
        try:
            return SubCustomer.query.all()
        except Exception as e:
            logging.error(f"Error fetching sub-customers: {e}", exc_info=True)
            raise ServiceError("Could not fetch sub-customers. Please try again later.")

    @staticmethod
    def get_by_id(sub_customer_id):
        try:
            return SubCustomer.query.get(sub_customer_id)
        except Exception as e:
            logging.error(f"Error fetching sub-customer: {e}", exc_info=True)
            raise ServiceError("Could not fetch sub-customer. Please try again later.")

    @staticmethod
    def create(data):
        try:
            sub_customer = SubCustomer(**data)
            db.session.add(sub_customer)
            db.session.commit()
            return sub_customer
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating sub-customer: {e}", exc_info=True)
            raise ServiceError("Could not create sub-customer. Please try again later.")

    @staticmethod
    def update(sub_customer_id, data):
        try:
            sub_customer = SubCustomer.query.get(sub_customer_id)
            if not sub_customer:
                return None
            for key, value in data.items():
                setattr(sub_customer, key, value)
            db.session.commit()
            return sub_customer
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating sub-customer: {e}", exc_info=True)
            raise ServiceError("Could not update sub-customer. Please try again later.")

    @staticmethod
    def delete(sub_customer_id):
        try:
            sub_customer = SubCustomer.query.get(sub_customer_id)
            if not sub_customer:
                return False
            db.session.delete(sub_customer)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting sub-customer: {e}", exc_info=True)
            raise ServiceError("Could not delete sub-customer. Please try again later.") 