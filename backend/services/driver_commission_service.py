import logging
from backend.extensions import db
from backend.models.driver_commission_table import DriverCommissionTable
from backend.models.driver import Driver

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class DriverCommissionService:
    @staticmethod
    def get_all():
        try:
            return DriverCommissionTable.query.all()
        except Exception as e:
            logging.error(f"Error fetching driver commissions: {e}", exc_info=True)
            raise ServiceError("Could not fetch driver commissions. Please try again later.")

    @staticmethod
    def get_by_id(commission_id):
        try:
            return DriverCommissionTable.query.get(commission_id)
        except Exception as e:
            logging.error(f"Error fetching driver commission: {e}", exc_info=True)
            raise ServiceError("Could not fetch driver commission. Please try again later.")

    @staticmethod
    def create(data):
        try:
            commission = DriverCommissionTable(**data)
            db.session.add(commission)
            db.session.commit()
            return commission
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating driver commission: {e}", exc_info=True)
            raise ServiceError("Could not create driver commission. Please try again later.")

    @staticmethod
    def update(commission_id, data):
        try:
            commission = DriverCommissionTable.query.get(commission_id)
            if not commission:
                return None
            for key, value in data.items():
                setattr(commission, key, value)
            db.session.commit()
            return commission
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating driver commission: {e}", exc_info=True)
            raise ServiceError("Could not update driver commission. Please try again later.")

    @staticmethod
    def delete(commission_id):
        try:
            commission = DriverCommissionTable.query.get(commission_id)
            if not commission:
                return False
            db.session.delete(commission)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting driver commission: {e}", exc_info=True)
            raise ServiceError("Could not delete driver commission. Please try again later.") 