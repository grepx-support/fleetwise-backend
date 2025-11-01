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
            return Service.query_active().all()
        except Exception as e:
            logging.error(f"Error fetching services: {e}", exc_info=True)
            raise ServiceError("Could not fetch services. Please try again later.")

    @staticmethod
    def get_by_id(service_id):
        try:
            return Service.query_active().filter_by(id=service_id).first()
        except Exception as e:
            logging.error(f"Error fetching service: {e}", exc_info=True)
            raise ServiceError("Could not fetch service. Please try again later.")

    @staticmethod
    def create(data):
        try:
            logging.info(f"Creating service with data: {list(data.keys())}")
            service = Service(**data)
            db.session.add(service)
            db.session.flush()  # Get the service ID without committing

            # Import here to avoid circular imports
            from backend.services.contractor_service_pricing_service import ContractorServicePricingService

            # Sync the new service to all active contractors
            try:
                success_count, error_count = ContractorServicePricingService.sync_new_service_to_contractors(service.id)
                if error_count > 0:
                    logging.warning(f"Some contractors ({error_count}) failed to sync with new service {service.id}")
            except Exception as sync_error:
                logging.error(f"Error syncing service to contractors: {sync_error}", exc_info=True)
                # Don't block service creation if sync fails
                
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
            service = Service.query_active().filter_by(id=service_id).first()
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
        try:
            service = Service.query_active().filter_by(id=service_id).first()
            if not service:
                return False

            # Soft delete the service instead of hard delete
            service.is_deleted = True

            db.session.commit()
            logging.info(f"Service {service_id} soft deleted successfully")
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting service: {e}", exc_info=True)
            raise ServiceError("Could not delete service. Please try again later.")

    @staticmethod
    def toggle_soft_delete(service_id, is_deleted):
        try:
            # Get service including deleted ones for restore functionality
            service = Service.query_all().filter_by(id=service_id).first()
            if not service:
                return None
            
            service.is_deleted = is_deleted
            
            db.session.commit()
            logging.info(f"Service {service_id} soft delete status toggled to {is_deleted}")
            return service
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error toggling service soft delete status: {e}", exc_info=True)
            raise ServiceError("Could not update service status. Please try again later.")