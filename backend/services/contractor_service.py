import logging
from backend.extensions import db
from backend.models.contractor import Contractor
from backend.models.contractor_service_pricing import ContractorServicePricing

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class ContractorService:
    @staticmethod
    def get_all():
        try:
            return Contractor.query_active().all()
        except Exception as e:
            logging.error(f"Error fetching contractors: {e}", exc_info=True)
            raise ServiceError("Could not fetch contractors. Please try again later.")

    @staticmethod
    def get_by_id(contractor_id):
        try:
            return Contractor.query_active().filter_by(id=contractor_id).first()
        except Exception as e:
            logging.error(f"Error fetching contractor: {e}", exc_info=True)
            raise ServiceError("Could not fetch contractor. Please try again later.")

    @staticmethod
    def create(data):
        try:
            contractor = Contractor(**data)
            db.session.add(contractor)
            db.session.commit()
            return contractor
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating contractor: {e}", exc_info=True)
            raise ServiceError("Could not create contractor. Please try again later.")

    @staticmethod
    def update(contractor_id, data):
        try:
            contractor = Contractor.query_active().filter_by(id=contractor_id).first()
            if not contractor:
                return None
            for key, value in data.items():
                setattr(contractor, key, value)
            db.session.commit()
            return contractor
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating contractor: {e}", exc_info=True)
            raise ServiceError("Could not update contractor. Please try again later.")

    @staticmethod
    def delete(contractor_id):
        try:
            contractor = Contractor.query_active().filter_by(id=contractor_id).first()
            if not contractor:
                return False
            # Soft delete the contractor instead of hard delete
            contractor.is_deleted = True
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting contractor: {e}", exc_info=True)
            raise ServiceError("Could not delete contractor. Please try again later.")

    @staticmethod
    def toggle_soft_delete(contractor_id, is_deleted):
        try:
            # Get contractor including deleted ones for restore functionality
            contractor = Contractor.query_all().filter_by(id=contractor_id).first()
            if not contractor:
                return None
            
            contractor.is_deleted = is_deleted
            db.session.commit()
            return contractor
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error toggling contractor soft delete status: {e}", exc_info=True)
            raise ServiceError("Could not update contractor status. Please try again later.")

    @staticmethod
    def get_active_contractors():
        try:
            return Contractor.query_active().filter_by(status='Active').all()
        except Exception as e:
            logging.error(f"Error fetching active contractors: {e}", exc_info=True)
            raise ServiceError("Could not fetch active contractors. Please try again later.")

    @staticmethod
    def get_contractor_pricing(contractor_id):
        try:
            return ContractorServicePricing.query.filter_by(contractor_id=contractor_id).all()
        except Exception as e:
            logging.error(f"Error fetching contractor pricing: {e}", exc_info=True)
            raise ServiceError("Could not fetch contractor pricing. Please try again later.")

    @staticmethod
    def update_contractor_pricing(contractor_id, service_id, cost):
        try:
            pricing = ContractorServicePricing.query.filter_by(
                contractor_id=contractor_id, 
                service_id=service_id
            ).first()
            
            if pricing:
                pricing.cost = cost
            else:
                pricing = ContractorServicePricing()
                pricing.contractor_id = contractor_id
                pricing.service_id = service_id
                pricing.cost = cost
                db.session.add(pricing)
            
            db.session.commit()
            return pricing
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating contractor pricing: {e}", exc_info=True)
            raise ServiceError("Could not update contractor pricing. Please try again later.")

    @staticmethod
    def get_contractor_cost_for_service(contractor_id, service_id):
        try:
            pricing = ContractorServicePricing.query.filter_by(
                contractor_id=contractor_id,
                service_id=service_id
            ).first()
            
            # Raise an exception if no pricing is found
            if not pricing:
                raise ServiceError(
                    f'No pricing configured for contractor {contractor_id} '
                    f'and service {service_id}. Cannot fetch cost.'
                )
            
            return pricing.cost
        except ServiceError:
            # Re-raise ServiceError as-is
            raise
        except Exception as e:
            logging.error(f"Error fetching contractor cost for service: {e}", exc_info=True)
            raise ServiceError("Could not fetch contractor cost for service. Please try again later.")

    @staticmethod
    def bulk_update_contractor_pricing(contractor_id, pricing_data):
        try:
            updated_pricing = []
            for pricing_item in pricing_data:
                service_id = pricing_item['service_id']
                cost = pricing_item['cost']
                
                pricing = ContractorServicePricing.query.filter_by(
                    contractor_id=contractor_id, 
                    service_id=service_id
                ).first()
                
                if pricing:
                    pricing.cost = cost
                else:
                    pricing = ContractorServicePricing()
                    pricing.contractor_id = contractor_id
                    pricing.service_id = service_id
                    pricing.cost = cost
                    db.session.add(pricing)
                
                updated_pricing.append(pricing)
            
            db.session.commit()
            return updated_pricing
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error bulk updating contractor pricing: {e}", exc_info=True)
            raise ServiceError("Could not bulk update contractor pricing. Please try again later.")

    @staticmethod
    def calculate_contractor_commission_for_job(job):
        """
        Calculate contractor commission for a job based on ContractorServicePricing.
        
        Args:
            job: Job object with contractor_id and service_id
            
        Returns:
            float: The contractor commission amount
        """
        try:
            # Check if job has both contractor_id and service_id
            if not job.contractor_id or not job.service_id:
                return 0.0
            
            # Get the pricing for this contractor and service combination
            pricing = ContractorServicePricing.query.filter_by(
                contractor_id=job.contractor_id,
                service_id=job.service_id
            ).first()
            
            # Raise an exception if no pricing is found
            if not pricing:
                raise ServiceError(
                    f'No pricing configured for contractor {job.contractor_id} '
                    f'and service {job.service_id}. Cannot calculate commission.'
                )
            
            # Return the cost from pricing
            return pricing.cost
        except ServiceError:
            # Re-raise ServiceError as-is
            raise
        except Exception as e:
            logging.error(f"Error calculating contractor commission for job {job.id}: {e}", exc_info=True)
            return 0.0
