import logging
from backend.extensions import db
from backend.models.vehicle_type import VehicleType

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class VehicleTypeService:
    @staticmethod
    def get_all():
        try:
            return VehicleType.query.all()
        except Exception as e:
            logging.error(f"Error fetching vehicle types: {e}", exc_info=True)
            raise ServiceError("Could not fetch vehicle types. Please try again later.")

    @staticmethod
    def get_by_id(vehicle_type_id):
        try:
            return VehicleType.query.get(vehicle_type_id)
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
            vehicle_type = VehicleType.query.get(vehicle_type_id)
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
        from backend.models.ServicesVehicleTypePrice import ServicesVehicleTypePrice
        try:
            vehicle_type = VehicleType.query.get(vehicle_type_id)
            if not vehicle_type:
                return False
            
            # Delete associated service vehicle type price records
            svc_price_count = ServicesVehicleTypePrice.query.filter_by(vehicle_type_id=vehicle_type_id).count()
            if svc_price_count > 0:
                ServicesVehicleTypePrice.query.filter_by(vehicle_type_id=vehicle_type_id).delete()
                logging.info(f"Cascade deleted {svc_price_count} service vehicle type price records for vehicle type {vehicle_type_id}")
            
            db.session.delete(vehicle_type)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting vehicle type: {e}", exc_info=True)
            raise ServiceError("Could not delete vehicle type. Please try again later.")