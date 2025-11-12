import logging
import uuid
from backend.extensions import db
from backend.models.user import User
from backend.models.customer import Customer
from backend.models.driver import Driver
from backend.models.role import Role
from flask_security.utils import hash_password
from sqlalchemy.exc import IntegrityError


class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class UserService:
    @staticmethod
    def _validate_entity_not_assigned(user_type, entity_id, exclude_user_id=None):
        # Allow multiple users to be assigned to the same customer
        # but keep restriction for drivers
        if user_type == 'driver':
            filter_field = 'driver_id'
            existing = User.query.filter_by(**{filter_field: entity_id}).first()
            if existing and (exclude_user_id is None or existing.id != exclude_user_id):
                raise ServiceError(f"{user_type.capitalize()} is already assigned to another user")
        # For customers, we allow multiple assignments, so no check is needed

    @staticmethod
    def get_all():
        try:
            return User.query.all()
        except Exception as e:
            logging.error(f"Error fetching users: {e}", exc_info=True)
            raise ServiceError("Could not fetch users. Please try again later.")

    @staticmethod
    def get_by_id(user_id):
        try:
            return User.query.get(user_id)
        except Exception as e:
            logging.error(f"Error fetching user: {e}", exc_info=True)
            raise ServiceError("Could not fetch user. Please try again later.")

    @staticmethod
    def create(data):
        try:
            # Validate and sanitize name field
            if 'name' in data:
                name = data['name']
                if name is not None:
                    if not isinstance(name, str):
                        raise ServiceError("Name must be a string")
                    name = name.strip()
                    if len(name) > 255:
                        raise ServiceError("Name cannot exceed 255 characters")
                    data['name'] = name if name else None
            
            password = data.pop('password', None)
            if password:
                data['password'] = hash_password(password)
            roles = data.pop('roles', [])
            role_names = data.pop('role_names', None)
            
            # Handle customer or driver assignment during creation
            customer_id = data.pop('customer_id', None)
            driver_id = data.pop('driver_id', None)
            
            # Ensure fs_uniquifier is set
            if 'fs_uniquifier' not in data or data['fs_uniquifier'] is None:
                data['fs_uniquifier'] = str(uuid.uuid4())
                
            user = User(**data)
            db.session.add(user)
            db.session.flush()
            
            # Handle customer assignment
            if customer_id:
                customer = Customer.query_active().filter_by(id=customer_id).first()
                if not customer:
                    raise ServiceError("Customer not found or inactive")
                UserService._validate_entity_not_assigned('customer', customer_id)
                user.customer_id = customer_id
            
            # Handle driver assignment
            if driver_id:
                driver = Driver.query_active().filter_by(id=driver_id).first()
                if not driver:
                    raise ServiceError("Driver not found or inactive")
                UserService._validate_entity_not_assigned('driver', driver_id)
                user.driver_id = driver_id
            
            # Handle roles - prefer role_names if provided
            roles_to_assign = role_names if role_names is not None else roles
            if roles_to_assign:
                for role_name in roles_to_assign:
                    role = Role.query.filter_by(name=role_name).first()
                    if role:
                        user.roles.append(role)
            db.session.commit()
            return user
        except IntegrityError:
            db.session.rollback()
            raise ServiceError("Driver is already assigned to another user")
        except ServiceError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating user: {e}", exc_info=True)
            raise ServiceError("Could not create user. Please try again later.")

    @staticmethod
    def update(user_id, data):
        try:
            user = User.query.get(user_id)
            if not user:
                return None
                
            # Validate and sanitize name field
            if 'name' in data:
                name = data['name']
                if name is not None:
                    if not isinstance(name, str):
                        raise ServiceError("Name must be a string")
                    name = name.strip()
                    if len(name) > 255:
                        raise ServiceError("Name cannot exceed 255 characters")
                    data['name'] = name if name else None
                
            password = data.pop('password', None)
            if password:
                user.password = hash_password(password)
            roles = data.pop('roles', None)
            role_names = data.pop('role_names', None)
            for key, value in data.items():
                setattr(user, key, value)
            # Handle roles update - prefer role_names if provided
            roles_to_assign = None
            if role_names is not None:
                roles_to_assign = role_names
            elif roles is not None:
                roles_to_assign = roles
                
            if roles_to_assign is not None:
                user.roles.clear()
                for role_name in roles_to_assign:
                    role = Role.query.filter_by(name=role_name).first()
                    if role:
                        user.roles.append(role)
            db.session.commit()
            return user
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating user: {e}", exc_info=True)
            raise ServiceError("Could not update user. Please try again later.")

    @staticmethod
    def delete(user_id):
        try:
            user = User.query.get(user_id)
            if not user:
                return False
            # Soft delete - set active to False instead of removing the record
            user.active = False
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting user: {e}", exc_info=True)
            raise ServiceError("Could not delete user. Please try again later.") 
    
    @staticmethod
    def save_device_token(driver_id: int, token_data: dict) -> bool:
        try:
            user = User.query.filter_by(driver_id=driver_id).first()

            if not user:
                raise ServiceError("User with provided driver_id not found.")

            android_token = token_data.get('android_device_token')
            ios_token = token_data.get('ios_device_token')

            if not android_token and not ios_token:
                raise ServiceError("No device token provided.")

            if android_token:
                user.android_device_token = android_token
            if ios_token:
                user.ios_device_token = ios_token

            db.session.commit()
            return True
        except ServiceError:
            raise 
        except Exception as e:
            logging.error(f"Failed to save device token: {e}", exc_info=True)
            raise ServiceError("An unexpected error occurred while saving device token.")

    @staticmethod
    def remove_device_tokens(driver_id: int) -> bool:
        try:
            user = User.query.filter_by(driver_id=driver_id).first()
            if not user:
                raise ServiceError("User with provided driver_id not found.")

            user.android_device_token = None
            user.ios_device_token = None
            db.session.commit()
            return True
        except ServiceError:
            raise
        except Exception as e:
            logging.error(f"Failed to remove device tokens: {e}", exc_info=True)
            raise ServiceError("An unexpected error occurred while removing device tokens.")

    @staticmethod
    def get_unassigned_customers():
        """
        Fetch all active customers (allows multiple user assignments)
        """
        try:
            # Since we're allowing multiple users per customer, 
            # this now returns all active customers
            all_customers = Customer.query_active().all()
            return all_customers
        except Exception as e:
            logging.error(f"Error fetching customers: {e}", exc_info=True)
            raise ServiceError("Could not fetch customers. Please try again later.")

    @staticmethod
    def get_unassigned_drivers():
        """
        Fetch drivers not assigned to any user
        """
        try:
            unassigned_drivers = Driver.query_active().filter(
                Driver.id.notin_(
                    db.session.query(User.driver_id).filter(User.driver_id.isnot(None))
                )
            ).all()
            return unassigned_drivers
        except Exception as e:
            logging.error(f"Error fetching unassigned drivers: {e}", exc_info=True)
            raise ServiceError("Could not fetch unassigned drivers. Please try again later.")

    @staticmethod
    def assign_customer_or_driver(user_id, user_type, entity_id):
        """
        Link users with customers or drivers
        """
        try:
            user = User.query.get(user_id)
            if not user:
                raise ServiceError("User not found")

            # Clear only the conflicting assignment
            if user_type == "customer":
                user.driver_id = None  # Clear driver when assigning customer
            elif user_type == "driver":
                user.customer_id = None  # Clear customer when assigning driver
            else:
                raise ServiceError("Invalid user type. Must be 'customer' or 'driver'")

            if user_type == "customer":
                customer = Customer.query_active().filter_by(id=entity_id).first()
                if not customer:
                    raise ServiceError("Customer not found")
                
                UserService._validate_entity_not_assigned('customer', entity_id, user_id)
                user.customer_id = entity_id
            elif user_type == "driver":
                driver = Driver.query_active().filter_by(id=entity_id).first()
                if not driver:
                    raise ServiceError("Driver not found")
                    
                UserService._validate_entity_not_assigned('driver', entity_id, user_id)
                user.driver_id = entity_id

            db.session.commit()
            return user
        except IntegrityError:
            db.session.rollback()
            if user_type == "customer":
                # This should not happen anymore since we allow multiple customer assignments
                raise ServiceError("An unexpected error occurred")
            else:
                raise ServiceError("Driver is already assigned to another user")
        except ServiceError:
            db.session.rollback()
            raise
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error assigning customer or driver: {e}", exc_info=True)
            raise ServiceError("Could not assign customer or driver. Please try again later.")
