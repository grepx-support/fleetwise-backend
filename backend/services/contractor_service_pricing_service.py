from backend.extensions import db
from backend.models.contractor_service_pricing import ContractorServicePricing
from backend.models.contractor import Contractor
from backend.models.vehicle_type import VehicleType
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
            logging.debug(f"Starting contractor sync for service {service_id}")

            # Get only active contractors - using the STATUS constant for consistency
            active_contractors = (
                db.session.query(Contractor)
                .filter(
                    Contractor.status == Contractor.STATUS_ACTIVE,
                    Contractor.is_deleted.is_(False)
                )
                .all()
            )

            logging.info(f"Found {len(active_contractors)} active contractors for service {service_id} sync")

            if not active_contractors:
                logging.info(f"No active contractors found for service {service_id} sync")
                return 0, 0

            # Get all vehicle types
            vehicle_types = db.session.query(VehicleType).filter(VehicleType.is_deleted.is_(False)).all()
            logging.info(f"Found {len(vehicle_types)} vehicle types for service {service_id} sync")

            success_count = 0
            error_count = 0

            # Process all contractors without committing individually
            for contractor in active_contractors:
                try:
                    # Double-check status hasn't changed (defensive programming)
                    if contractor.status != Contractor.STATUS_ACTIVE:
                        logging.info(
                            f"Skipping contractor {contractor.id} - status changed to {contractor.status}"
                        )
                        continue

                    # For each vehicle type, create a pricing entry
                    for vehicle_type in vehicle_types:
                        # Check if pricing already exists (defensive programming)
                        existing = ContractorServicePricing.query.filter_by(
                            contractor_id=contractor.id,
                            service_id=service_id,
                            vehicle_type_id=vehicle_type.id
                        ).first()

                        if existing:
                            logging.warning(
                                f"Pricing already exists for contractor {contractor.id}, "
                                f"service {service_id}, and vehicle type {vehicle_type.id}, skipping"
                            )
                            continue

                        # Create new pricing entry with default values
                        pricing = ContractorServicePricing()
                        pricing.contractor_id = contractor.id
                        pricing.service_id = service_id
                        pricing.vehicle_type_id = vehicle_type.id
                        pricing.cost = 0.0
                        db.session.add(pricing)
                    
                    success_count += 1
                    logging.debug(f"Added pricing for contractor {contractor.id} and service {service_id} for all vehicle types")

                except IntegrityError as ie:
                    error_count += 1
                    logging.error(
                        f"Integrity error syncing service {service_id} to contractor {contractor.id}: {str(ie)}"
                    )
                    # Continue processing other contractors - we'll rollback all at the end if needed
                except Exception as e:
                    error_count += 1
                    logging.error(
                        f"Error syncing service {service_id} to contractor {contractor.id}: {str(e)}"
                    )
                    # Continue processing other contractors - we'll rollback all at the end if needed

            # Single commit for entire batch to ensure atomicity
            db.session.commit()
            logging.info(
                f"Successfully synced service {service_id} to {success_count} active contractors "
                f"({error_count} errors)"
            )

            return success_count, error_count

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in sync_new_service_to_contractors: {str(e)}", exc_info=True)
            raise ContractorServicePricingError("Failed to sync service to contractors. Please check the logs.")

    @staticmethod
    def get_pricing(contractor_id, service_id, vehicle_type_id):
        """
        Get pricing for a specific contractor, service, and vehicle type combination.

        Args:
            contractor_id (int): The contractor ID
            service_id (int): The service ID
            vehicle_type_id (int): The vehicle type ID

        Returns:
            ContractorServicePricing: The pricing record or None if not found
        """
        return ContractorServicePricing.query.filter_by(
            contractor_id=contractor_id,
            service_id=service_id,
            vehicle_type_id=vehicle_type_id
        ).first()

    @staticmethod
    def update_pricing(contractor_id, service_id, vehicle_type_id, cost=None):
        """
        Update pricing by delegating to ContractorService to maintain single source of truth.
        
        Args:
            contractor_id (int): The contractor ID
            service_id (int): The service ID
            vehicle_type_id (int): The vehicle type ID
            cost (float, optional): The cost value

        Returns:
            ContractorServicePricing: The updated pricing record
        """
        from backend.services.contractor_service import ContractorService
        if cost is None:
            cost = 0.0
        return ContractorService.update_contractor_pricing(
            contractor_id, service_id, vehicle_type_id, cost
        )