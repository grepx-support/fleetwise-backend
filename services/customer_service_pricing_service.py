from backend.extensions import db
from backend.models.customer_service_pricing import CustomerServicePricing
from sqlalchemy.exc import IntegrityError
from backend.models.service import Service
from backend.models.vehicle_type import VehicleType


UQ_NAMES = (
    "uq_csp_cust_service_vehicle",   # new name from your migration
    "_cust_service_pricing_uc",      # old name (kept for safety)
)

class CustomerServicePricingService:
    """Service for customer service pricing operations"""

    @staticmethod
    def create(data: dict) -> CustomerServicePricing:
        try:
            pricing = CustomerServicePricing(**data)
            db.session.add(pricing)
            db.session.commit()
            return pricing
        except IntegrityError as e:
            db.session.rollback()
            msg = str(e.orig) if getattr(e, "orig", None) else str(e)
            if "UNIQUE constraint failed" in msg or any(n in msg for n in UQ_NAMES):
                raise ValueError("Pricing record already exists for this customer/service/vehicle combination")
            elif "FOREIGN KEY constraint failed" in msg:
                raise ValueError("Invalid foreign key (customer, service, or vehicle type)")
            raise ValueError(f"Database constraint violation: {msg}")

    @staticmethod
    def get_all(cust_id: int | None = None,
                service_id: int | None = None,
                vehicle_type_id: int | None = None):
        q = CustomerServicePricing.query
        if cust_id is not None:
            q = q.filter_by(cust_id=cust_id)
        if service_id is not None:
            q = q.filter_by(service_id=service_id)
        if vehicle_type_id is not None:
            q = q.filter_by(vehicle_type_id=vehicle_type_id)
        return q.all()

    @staticmethod
    def get_by_id(pricing_id: int):
        return CustomerServicePricing.query.get(pricing_id)

    @staticmethod
    def get_by_customer_and_service(cust_id: int, service_id: int):
        """Return ALL rows for this customer+service across vehicle types."""
        return CustomerServicePricing.query.filter_by(
            cust_id=cust_id, service_id=service_id
        ).all()
        
    @staticmethod
    def get_by_customer_service_and_vehicle(cust_id: int, service_id: int, vehicle_type_id: int):
        """Return pricing for specific customer, service, and vehicle type."""
        return CustomerServicePricing.query.filter_by(
            cust_id=cust_id, service_id=service_id, vehicle_type_id=vehicle_type_id
        ).first()

    @staticmethod
    def update(pricing_id: int, data: dict):
        pricing = CustomerServicePricing.query.get(pricing_id)
        if not pricing:
            return None
        try:
            for k, v in data.items():
                setattr(pricing, k, v)
            db.session.commit()
            return pricing
        except IntegrityError as e:
            db.session.rollback()
            msg = str(e.orig) if getattr(e, "orig", None) else str(e)
            if "UNIQUE constraint failed" in msg or any(n in msg for n in UQ_NAMES):
                raise ValueError("Pricing record already exists for this customer/service/vehicle combination")
            elif "FOREIGN KEY constraint failed" in msg:
                raise ValueError("Invalid foreign key (customer, service, or vehicle type)")
            raise ValueError(f"Database constraint violation: {msg}")
        except Exception as e:
            db.session.rollback()
            raise ValueError(f"Failed to update pricing record: {str(e)}")

    @staticmethod
    def delete(pricing_id: int) -> bool:
        pricing = CustomerServicePricing.query.get(pricing_id)
        if not pricing:
            return False
        try:
            db.session.delete(pricing)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            raise ValueError(f"Failed to delete pricing record: {str(e)}")

    @staticmethod
    def upsert_bulk(db, items):
        with db.session.begin():  # single tx for the batch
            for i in items:
                cust_id = i["cust_id"]
                vt_id = i["vehicle_type_id"]
                svc_id = i["service_id"]
                price  = i.get("price")

                # lock existing row if present
                row = (
                    db.session.query(CustomerServicePricing)
                    .filter_by(cust_id=cust_id, vehicle_type_id=vt_id, service_id=svc_id)
                    .with_for_update()  # row-level lock
                    .one_or_none()
                )

                if price is None:
                    if row:
                        db.session.delete(row)
                    # if no row, nothing to do
                    continue

                if row:
                    row.price = price
                    continue

                if not db.session.query(Service).get(svc_id):
                    raise ValueError(f"Service {svc_id} missing")
                if not db.session.query(VehicleType).get(vt_id):
                    raise ValueError(f"VehicleType {vt_id} missing")

                # Row not found -> try insert; if another tx inserts first, catch and update
                try:
                    db.session.add(CustomerServicePricing(
                        cust_id=cust_id, vehicle_type_id=vt_id, service_id=svc_id, price=price
                    ))
                    db.session.flush()  # force the INSERT now to surface IntegrityError here
                except IntegrityError:
                    db.session.rollback()  # rolls back to savepoint within `begin()`; tx remains open
                    # Now fetch the row (it should exist) and update it under lock
                    row = (
                        db.session.query(CustomerServicePricing)
                        .filter_by(cust_id=cust_id, vehicle_type_id=vt_id, service_id=svc_id)
                        .with_for_update()
                        .one()
                    )
                    row.price = price