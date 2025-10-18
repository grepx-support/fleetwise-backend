import logging
import uuid
from backend.extensions import db
from backend.models.user import User
from backend.models.role import Role
from flask_security.utils import hash_password

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class UserService:
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
            password = data.pop('password', None)
            if password:
                data['password'] = hash_password(password)
            roles = data.pop('roles', [])
            role_names = data.pop('role_names', None)
            
            # Ensure fs_uniquifier is set
            if 'fs_uniquifier' not in data or data['fs_uniquifier'] is None:
                data['fs_uniquifier'] = str(uuid.uuid4())
                
            user = User(**data)
            db.session.add(user)
            db.session.flush()
            # Handle roles - prefer role_names if provided
            roles_to_assign = role_names if role_names is not None else roles
            if roles_to_assign:
                for role_name in roles_to_assign:
                    role = Role.query.filter_by(name=role_name).first()
                    if role:
                        user.roles.append(role)
            db.session.commit()
            return user
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