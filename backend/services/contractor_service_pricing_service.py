from backend.extensions import db
from backend.models.contractor_service_pricing import ContractorServicePricing
from backend.models.contractor import Contractor
from sqlalchemy.exc import IntegrityError
import logging

class ContractorServicePricingError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class ContractorServicePricingService:
    @staticmethod
    def sync_new_service_to_contractors(service_id):
        """
        Sync a newly created service to all active contractors' pricing lists.
        
        Args:
            service_id (int): The ID of the newly created service
            
        Returns:
            tuple: (success_count, error_count) - Number of successful and failed syncs
        """
        try:
            # Log all contractors and their statuses for debugging
            all_contractors = Contractor.query.all()
            for c in all_contractors:
                logging.info(f"DEBUG - Found Contractor - ID: {c.id}, Name: {c.name}, Status: {c.status}, Is_Deleted: {c.is_deleted}")

            # Get only active contractors - using the STATUS constant for consistency
            active_contractors = (
                db.session.query(Contractor)
                .filter(
                    Contractor.status == Contractor.STATUS_ACTIVE,  # Exact match with 'Active'
                    Contractor.is_deleted.is_(False)  # Explicitly check for not deleted
                )
                .all()
            )
            
            # Log selected active contractors
            logging.info(f"DEBUG - Found {len(active_contractors)} active contractors")
            for c in active_contractors:
                logging.info(f"DEBUG - Selected Active - ID: {c.id}, Name: {c.name}, Status: {c.status}")
            
            if not active_contractors:
                logging.info(f"No active contractors found for service {service_id} sync")
                return 0, 0
            
            success_count = 0
            error_count = 0
            
            for contractor in active_contractors:
                try:
                    # Double-check status hasn't changed (defensive programming)
                    if contractor.status != Contractor.STATUS_ACTIVE:
                        logging.info(
                            f"Skipping contractor {contractor.id} - status changed to {contractor.status}"
                        )
                        continue
                    
                    # Check if pricing already exists (defensive programming)
                    existing = ContractorServicePricing.query.filter_by(
                        contractor_id=contractor.id,
                        service_id=service_id
                    ).first()
                    
                    if existing:
                        logging.warning(
                            f"Pricing already exists for contractor {contractor.id} "
                            f"and service {service_id}, skipping"
                        )
                        continue
                    
                    # Create new pricing entry with default price $0.00
                    pricing = ContractorServicePricing(
                        contractor_id=contractor.id,
                        service_id=service_id,
                        cost=0.0
                    )
                    db.session.add(pricing)
                    success_count += 1
                    logging.debug(f"Added pricing for contractor {contractor.id} and service {service_id}")
                    
                except IntegrityError as ie:
                    error_count += 1
                    db.session.rollback()  # Rollback this transaction
                    logging.error(
                        f"Integrity error syncing service {service_id} to contractor {contractor.id}: {str(ie)}",
                        exc_info=True
                    )
                except Exception as e:
                    error_count += 1
                    db.session.rollback()  # Rollback this transaction
                    logging.error(
                        f"Error syncing service {service_id} to contractor {contractor.id}: {str(e)}",
                        exc_info=True
                    )
            
            # Commit all successful additions at once
            if success_count > 0:
                db.session.commit()
                logging.info(
                    f"Successfully synced service {service_id} to {success_count} active contractors "
                    f"({error_count} errors)"
                )
            else:
                logging.info(f"No contractors were synced for service {service_id}")
            
            return success_count, error_count
            
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in sync_new_service_to_contractors: {str(e)}", exc_info=True)
            raise ContractorServicePricingError("Failed to sync service to contractors. Please check the logs.")