import logging
from backend.extensions import db
from backend.models.ServicesVehicleTypePrice import ServicesVehicleTypePrice
from sqlalchemy.exc import IntegrityError

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class ServicesVehicleTypePriceService:
    @staticmethod
    def get_all():
        try:
            return ServicesVehicleTypePrice.query.all()
        except Exception as e:
            logging.error(f"Error fetching service vehicle type prices: {e}", exc_info=True)
            raise ServiceError("Could not fetch service vehicle type prices. Please try again later.")

    @staticmethod
    def get_by_id(service_vehicle_type_price_id):
        try:
            return ServicesVehicleTypePrice.query.get(service_vehicle_type_price_id)
        except Exception as e:
            logging.error(f"Error fetching service vehicle type price: {e}", exc_info=True)
            raise ServiceError("Could not fetch service vehicle type price. Please try again later.")

    @staticmethod
    def get_by_service_id(service_id):
        try:
            return ServicesVehicleTypePrice.query.filter_by(service_id=service_id).all()
        except Exception as e:
            logging.error(f"Error fetching service vehicle type prices for service {service_id}: {e}", exc_info=True)
            raise ServiceError("Could not fetch service vehicle type prices. Please try again later.")

    @staticmethod
    def create(data):
        try:
            service_vehicle_type_price = ServicesVehicleTypePrice(**data)
            db.session.add(service_vehicle_type_price)
            db.session.commit()
            return service_vehicle_type_price
        except IntegrityError as e:
            db.session.rollback()
            logging.error(f"Integrity error creating service vehicle type price: {e}", exc_info=True)
            # Check if it's a duplicate entry error
            if "UNIQUE constraint failed" in str(e) or "duplicate" in str(e).lower():
                raise ServiceError("A pricing entry already exists for this service and vehicle type combination.")
            else:
                raise ServiceError("Could not create service vehicle type price due to a data conflict. Please check your inputs.")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating service vehicle type price: {e}", exc_info=True)
            raise ServiceError("Could not create service vehicle type price. Please try again later.")

    @staticmethod
    def update(service_vehicle_type_price_id, data):
        try:
            service_vehicle_type_price = ServicesVehicleTypePrice.query.get(service_vehicle_type_price_id)
            if not service_vehicle_type_price:
                return None
            for key, value in data.items():
                setattr(service_vehicle_type_price, key, value)
            db.session.commit()
            return service_vehicle_type_price
        except IntegrityError as e:
            db.session.rollback()
            logging.error(f"Integrity error updating service vehicle type price: {e}", exc_info=True)
            # Check if it's a duplicate entry error
            if "UNIQUE constraint failed" in str(e) or "duplicate" in str(e).lower():
                raise ServiceError("A pricing entry already exists for this service and vehicle type combination.")
            else:
                raise ServiceError("Could not update service vehicle type price due to a data conflict. Please check your inputs.")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating service vehicle type price: {e}", exc_info=True)
            raise ServiceError("Could not update service vehicle type price. Please try again later.")

    @staticmethod
    def delete(service_vehicle_type_price_id):
        try:
            service_vehicle_type_price = ServicesVehicleTypePrice.query.get(service_vehicle_type_price_id)
            if not service_vehicle_type_price:
                return False
            db.session.delete(service_vehicle_type_price)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting service vehicle type price: {e}", exc_info=True)
            raise ServiceError("Could not delete service vehicle type price. Please try again later.")