import logging
from backend.models.service import Service
from backend.extensions import db
from sqlalchemy.exc import IntegrityError

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class ServiceService:
    @staticmethod
    def get_all():
        try:
            return Service.query.all()
        except Exception as e:
            logging.error(f"Error fetching services: {e}", exc_info=True)
            raise ServiceError("Could not fetch services. Please try again later.")

    @staticmethod
    def get_by_id(service_id):
        try:
            return Service.query.get(service_id)
        except Exception as e:
            logging.error(f"Error fetching service: {e}", exc_info=True)
            raise ServiceError("Could not fetch service. Please try again later.")

    @staticmethod
    def create(data):
        try:
            logging.info(f"Creating service with data: {list(data.keys())}")
            service = Service(**data)
            db.session.add(service)
            db.session.commit()
            logging.info(f"Service created successfully with ID: {service.id}")
            return service
        except IntegrityError as e:
            db.session.rollback()
            logging.error(f"Integrity error creating service: {e}", exc_info=True)
            # Check if it's a duplicate name error
            if "UNIQUE constraint failed" in str(e) and "service.name" in str(e):
                raise ServiceError("A service with this name already exists. Please choose a different name.")
            else:
                raise ServiceError("Could not create service due to a data conflict. Please check your inputs.")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating service: {e}", exc_info=True)
            raise ServiceError("Could not create service. Please try again later.")

    @staticmethod
    def update(service_id, data):
        try:
            logging.info(f"Updating service {service_id} with data: {list(data.keys())}")
            service = Service.query.get(service_id)
            if not service:
                return None
            for key, value in data.items():
                setattr(service, key, value)
            db.session.commit()
            logging.info(f"Service {service_id} updated successfully")
            return service
        except IntegrityError as e:
            db.session.rollback()
            logging.error(f"Integrity error updating service: {e}", exc_info=True)
            # Check if it's a duplicate name error
            if "UNIQUE constraint failed" in str(e) and "service.name" in str(e):
                raise ServiceError("A service with this name already exists. Please choose a different name.")
            else:
                raise ServiceError("Could not update service due to a data conflict. Please check your inputs.")
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating service: {e}", exc_info=True)
            raise ServiceError("Could not update service. Please try again later.")

    @staticmethod
    def delete(service_id):
        from backend.models.customer_service_pricing import CustomerServicePricing
        from backend.models.ServicesVehicleTypePrice import ServicesVehicleTypePrice
        try:
            service = Service.query.get(service_id)
            if not service:
                return False
            
            # Delete associated customer service pricing records
            pricing_count = CustomerServicePricing.query.filter_by(service_id=service_id).count()
            if pricing_count > 0:
                CustomerServicePricing.query.filter_by(service_id=service_id).delete()
                logging.info(f"Cascade deleted {pricing_count} customer service pricing records for service {service_id}")
            
            # Delete associated service vehicle type price records
            svc_price_count = ServicesVehicleTypePrice.query.filter_by(service_id=service_id).count()
            if svc_price_count > 0:
                ServicesVehicleTypePrice.query.filter_by(service_id=service_id).delete()
                logging.info(f"Cascade deleted {svc_price_count} service vehicle type price records for service {service_id}")
            
            db.session.delete(service)
            db.session.commit()
            logging.info(f"Service {service_id} deleted successfully")
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting service: {e}", exc_info=True)
            raise ServiceError("Could not delete service. Please try again later.")
