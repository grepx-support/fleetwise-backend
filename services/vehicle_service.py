import logging
from backend.extensions import db
from backend.models.vehicle import Vehicle
from backend.models.driver import Driver

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class VehicleService:
    @staticmethod
    def get_all():
        try:
            return Vehicle.query.all()
        except Exception as e:
            logging.error(f"Error fetching vehicles: {e}", exc_info=True)
            raise ServiceError("Could not fetch vehicles. Please try again later.")

    @staticmethod
    def get_by_id(vehicle_id):
        try:
            return Vehicle.query.get(vehicle_id)
        except Exception as e:
            logging.error(f"Error fetching vehicle: {e}", exc_info=True)
            raise ServiceError("Could not fetch vehicle. Please try again later.")

    @staticmethod
    def create(data):
        try:
            vehicle = Vehicle(**data)
            db.session.add(vehicle)
            db.session.commit()
            return vehicle
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating vehicle: {e}", exc_info=True)
            raise ServiceError("Could not create vehicle. Please try again later.")

    @staticmethod
    def update(vehicle_id, data):
        try:
            vehicle = Vehicle.query.get(vehicle_id)
            if not vehicle:
                return None
            for key, value in data.items():
                setattr(vehicle, key, value)
            db.session.commit()
            return vehicle
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating vehicle: {e}", exc_info=True)
            raise ServiceError("Could not update vehicle. Please try again later.")

    @staticmethod
    def delete(vehicle_id):
        try:
            vehicle = Vehicle.query.get(vehicle_id)
            if not vehicle:
                return False
            db.session.delete(vehicle)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting vehicle: {e}", exc_info=True)
            raise ServiceError("Could not delete vehicle. Please try again later.") 