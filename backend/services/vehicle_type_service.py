import logging
from backend.extensions import db
from backend.models.vehicle_type import VehicleType
from backend.models.ServicesVehicleTypePrice import ServicesVehicleTypePrice

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class VehicleTypeService:
    @staticmethod
    def get_all():
        try:
            return VehicleType.query_active().all()
        except Exception as e:
            logging.error(f"Error fetching vehicle types: {e}", exc_info=True)
            raise ServiceError("Could not fetch vehicle types. Please try again later.")

    @staticmethod
    def get_by_id(vehicle_type_id):
        try:
            return VehicleType.query_active().filter_by(id=vehicle_type_id).first()
        except Exception as e:
            logging.error(f"Error fetching vehicle type: {e}", exc_info=True)
            raise ServiceError("Could not fetch vehicle type. Please try again later.")

    @staticmethod
    def create(data):
        try:
            vehicle_type = VehicleType(**data)
            db.session.add(vehicle_type)
            db.session.commit()
            return vehicle_type
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating vehicle type: {e}", exc_info=True)
            raise ServiceError("Could not create vehicle type. Please try again later.")

    @staticmethod
    def update(vehicle_type_id, data):
        try:
            vehicle_type = VehicleType.query_active().filter_by(id=vehicle_type_id).first()
            if not vehicle_type:
                return None
            for key, value in data.items():
                setattr(vehicle_type, key, value)
            db.session.commit()
            return vehicle_type
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating vehicle type: {e}", exc_info=True)
            raise ServiceError("Could not update vehicle type. Please try again later.")

    @staticmethod
    def delete(vehicle_type_id):
        try:
            vehicle_type = VehicleType.query_active().filter_by(id=vehicle_type_id).first()
            if not vehicle_type:
                return False
            
            # Soft delete the vehicle type instead of hard delete
            vehicle_type.is_deleted = True
            
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting vehicle type: {e}", exc_info=True)
            raise ServiceError("Could not delete vehicle type. Please try again later.")

    @staticmethod
    def toggle_soft_delete(vehicle_type_id, is_deleted):
        try:
            # Get vehicle type including deleted ones for restore functionality
            vehicle_type = VehicleType.query_all().filter_by(id=vehicle_type_id).first()
            if not vehicle_type:
                return None
            
            vehicle_type.is_deleted = is_deleted
            
            db.session.commit()
            return vehicle_type
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error toggling vehicle type soft delete status: {e}", exc_info=True)
            raise ServiceError("Could not update vehicle type status. Please try again later.")