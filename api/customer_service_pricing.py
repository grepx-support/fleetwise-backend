from flask import Blueprint, request, jsonify
from marshmallow import ValidationError
from backend.schemas.customer_service_pricing_schema import CustomerServicePricingSchema
from backend.services.customer_service_pricing_service import CustomerServicePricingService
from backend.models.customer import Customer
from backend.models.service import Service
from flask_security import roles_accepted
from backend.models.vehicle_type import VehicleType
from backend.models.ServicesVehicleTypePrice import ServicesVehicleTypePrice as SVTP
from sqlalchemy import select
from backend.extensions import db
from backend.models.customer_service_pricing import CustomerServicePricing


customer_service_pricing_bp = Blueprint('customer_service_pricing', __name__)
schema = CustomerServicePricingSchema()

@customer_service_pricing_bp.route('/customer_service_pricing', methods=['POST'], strict_slashes=False)
@roles_accepted('admin', 'manager')
def create_customer_service_pricing():
    """Create a new customer service pricing record"""
    try:
        data = schema.load(request.json)
        
        # Validate that customer and service exist
        if not Customer.query.get(data['cust_id']):
            return jsonify({'error': 'Customer not found'}), 400
        if not Service.query.get(data['service_id']):
            return jsonify({'error': 'Service not found'}), 400
            
        pricing = CustomerServicePricingService.create(data)
        return jsonify(schema.dump(pricing)), 201
    except ValidationError as err:
        return jsonify(err.messages), 400
    except ValueError as e:
        # Handle constraint violations with appropriate status codes
        if "already exists" in str(e):
            return jsonify({'error': str(e)}), 409  # Conflict
        else:
            return jsonify({'error': str(e)}), 400  # Bad Request
    except Exception as e:
        return jsonify({'error': 'Could not create pricing record'}), 500

@customer_service_pricing_bp.route('/customer_service_pricing', methods=['GET'], strict_slashes=False)
@roles_accepted('admin', 'manager')
def get_customer_service_pricing():
    """Get all customer service pricing records"""
    try:
        cust_id = request.args.get('cust_id', type=int)
        pricing_records = CustomerServicePricingService.get_all(cust_id=cust_id)
        return jsonify(schema.dump(pricing_records, many=True)), 200
    except Exception as e:
        return jsonify({'error': 'Could not fetch pricing records'}), 500

@customer_service_pricing_bp.route('/customer_service_pricing/<int:pricing_id>', methods=['GET'])
@roles_accepted('admin', 'manager')
def get_customer_service_pricing_by_id(pricing_id):
    """Get customer service pricing record by ID"""
    try:
        pricing = CustomerServicePricingService.get_by_id(pricing_id)
        if not pricing:
            return jsonify({'error': 'Pricing record not found'}), 404
        return jsonify(schema.dump(pricing)), 200
    except Exception as e:
        return jsonify({'error': 'Could not fetch pricing record'}), 500

@customer_service_pricing_bp.route('/customer_service_pricing/customer/<int:cust_id>/service/<int:service_id>', methods=['GET'])
@roles_accepted('admin', 'manager')
def get_customer_service_pricing_by_customer_and_service(cust_id, service_id):
    """Get customer service pricing record by customer ID and service ID"""
    try:
        rows = CustomerServicePricingService.get_by_customer_and_service(cust_id, service_id)
        if not rows:
            return jsonify([]), 200
        return jsonify(schema.dump(rows, many=True)), 200

    except Exception as e:
        return jsonify({'error': 'Could not fetch pricing record'}), 500

@customer_service_pricing_bp.route('/customer_service_pricing/lookup', methods=['GET'])
@roles_accepted('admin', 'manager')
def get_customer_service_pricing_lookup():
    """Get customer service pricing record by customer ID, service name, and vehicle type"""
    try:
        cust_id = request.args.get('cust_id', type=int)
        service_name = request.args.get('service_name')
        vehicle_type_name = request.args.get('vehicle_type')
        
        # All three parameters are mandatory
        if not cust_id:
            return jsonify({'error': 'cust_id is required'}), 400
        if not service_name:
            return jsonify({'error': 'service_name is required'}), 400
        if not vehicle_type_name:
            return jsonify({'error': 'vehicle_type is required'}), 400
        
        # Find service by name
        service = Service.query.filter_by(name=service_name).first()
        if not service:
            return jsonify({'error': 'service not found'}), 404
            
        # Find the vehicle type
        vehicle_type = VehicleType.query.filter_by(name=vehicle_type_name).first()
        if not vehicle_type:
            return jsonify({'error': 'vehicle type not found'}), 404
        
        # Get pricing for specific customer, service, and vehicle type
        pricing = CustomerServicePricingService.get_by_customer_service_and_vehicle(
            cust_id, service.id, vehicle_type.id
        )
        
        # If no pricing record found with all three fields, return 0
        if not pricing:
            return jsonify({'price': 0}), 200
            
        # If pricing record found, return the price
        return jsonify({'price': pricing.price}), 200
    except Exception as e:
        return jsonify({'error': 'Could not fetch pricing record'}), 500

@customer_service_pricing_bp.route('/customer_service_pricing/<int:pricing_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_customer_service_pricing(pricing_id):
    """Update customer service pricing record"""
    try:
        data = schema.load(request.json, partial=True)
        
        # Validate that customer and service exist if they're being updated
        if 'cust_id' in data and not Customer.query.get(data['cust_id']):
            return jsonify({'error': 'Customer not found'}), 400
        if 'service_id' in data and not Service.query.get(data['service_id']):
            return jsonify({'error': 'Service not found'}), 400
            
        pricing = CustomerServicePricingService.update(pricing_id, data)
        if not pricing:
            return jsonify({'error': 'Pricing record not found'}), 404
        return jsonify(schema.dump(pricing)), 200
    except ValidationError as err:
        return jsonify(err.messages), 400
    except ValueError as e:
        # Handle constraint violations with appropriate status codes
        if "already exists" in str(e):
            return jsonify({'error': str(e)}), 409  # Conflict
        else:
            return jsonify({'error': str(e)}), 400  # Bad Request
    except Exception as e:
        return jsonify({'error': 'Could not update pricing record'}), 500

@customer_service_pricing_bp.route('/customer_service_pricing/<int:pricing_id>', methods=['DELETE'], strict_slashes=False)
@roles_accepted('admin', 'manager')
def delete_customer_service_pricing(pricing_id):
    """Delete customer service pricing record"""
    try:
        success = CustomerServicePricingService.delete(pricing_id)
        if not success:
            return jsonify({'error': 'Pricing record not found'}), 404
        return jsonify({'message': 'Pricing record deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': 'Could not delete pricing record'}), 500
    
@customer_service_pricing_bp.route('/pricing-matrix/defaults', methods=['GET'])
@roles_accepted('admin', 'manager')
def pricing_defaults_matrix():
    services = Service.query.order_by(Service.id).all()
    vehicles = VehicleType.query.order_by(VehicleType.id).all()

    # (service_id, vehicle_type_id) -> price
    rows = SVTP.query.with_entities(SVTP.service_id, SVTP.vehicle_type_id, SVTP.price).all()
    dmap = {(s, v): float(p) if p is not None else None for (s, v, p) in rows}

    matrix = []
    for vt in vehicles:
        matrix.append({
            "vehicle_type_id": vt.id,
            "vehicle_type_name": vt.name,
            "prices": {str(s.id): dmap.get((s.id, vt.id)) for s in services}
        })

    return jsonify({
        "services": [{"id": s.id, "name": s.name} for s in services],
        "vehicle_types": [{"id": vt.id, "name": vt.name} for vt in vehicles],
        "matrix": matrix
    })

@customer_service_pricing_bp.route('/customers/<int:cust_id>/pricing-matrix', methods=['GET'])
@roles_accepted('admin', 'manager')
def get_pricing_matrix(cust_id: int):
    services = Service.query.all()
    vehicle_types = VehicleType.query.all()

    # Bulk fetch all defaults and overrides
    defaults = SVTP.query.all()
    dmap = {(d.service_id, d.vehicle_type_id): d.price for d in defaults}
    overrides = CustomerServicePricing.query.filter_by(cust_id=cust_id).all()
    omap = {(o.service_id, o.vehicle_type_id): o.price for o in overrides}

    matrix = []
    for vt in vehicle_types:
        row = {"vehicle_type_id": vt.id, "vehicle_type_name": vt.name, "prices": {}}
        for svc in services:
            key = (svc.id, vt.id)
            # Use override if present, else default
            price = omap.get(key)
            if price is None:
                price = dmap.get(key)
            row["prices"][str(svc.id)] = price
        matrix.append(row)

    return {
        "matrix": matrix,
        "services": [{"id": s.id, "name": s.name} for s in services],
        "vehicle_types": [{"id": vt.id, "name": vt.name} for vt in vehicle_types],
    }


@customer_service_pricing_bp.route('/customers/<int:cust_id>/pricing-matrix', methods=['POST'])
@roles_accepted('admin', 'manager')
def save_pricing_customer_matrix(cust_id):
    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    norm = []
    for it in items:
        try:
            sid = int(it["service_id"])
            vid = int(it["vehicle_type_id"])
            price_raw = it.get("price")
            if price_raw not in ("", None):
                p = float(price_raw)
                if p < 0:
                    return jsonify({"error": "Negative invalid"}), 400
                price = p
            else:
                price = None

            # Query default price for this service/vehicle
            default = SVTP.query.filter_by(service_id=sid, vehicle_type_id=vid).first()
            default_price = default.price if default else None

            # Only store if different from default
            if price != default_price:
                norm.append({
                    "service_id": sid,
                    "vehicle_type_id": vid,
                    "price": price
                })
        except Exception:
            return jsonify({"error": "Invalid item format"}), 400

    count = CustomerServicePricingService.upsert_bulk(cust_id, norm)
    return jsonify({"ok": True, "count": count}), 200

@customer_service_pricing_bp.route('/customer_with_pricing', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_customer_with_pricing():
    """
    Atomically create a customer and their pricing overrides in one transaction.
    Expects JSON: { ...customer_fields, pricing: [{service_id, vehicle_type_id, price}, ...] }
    """
    data = request.get_json()
    cust_data = {k: v for k, v in data.items() if k != 'pricing'}
    pricing_items = data.get('pricing', [])

    try:
        # Create customer
        customer = Customer(**cust_data)
        db.session.add(customer)
        db.session.flush()  # get customer.id

        # Add pricing overrides (if any)
        for item in pricing_items:
            db.session.add(CustomerServicePricing(
                cust_id=customer.id,
                service_id=item["service_id"],
                vehicle_type_id=item["vehicle_type_id"],
                price=item["price"]
            ))

        db.session.commit()
        return jsonify({"id": customer.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
