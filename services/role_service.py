import logging
from backend.extensions import db
from backend.models.role import Role

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class RoleService:
    @staticmethod
    def get_all():
        try:
            return Role.query.all()
        except Exception as e:
            logging.error(f"Error fetching roles: {e}", exc_info=True)
            raise ServiceError("Could not fetch roles. Please try again later.")

    @staticmethod
    def get_by_id(role_id):
        try:
            return Role.query.get(role_id)
        except Exception as e:
            logging.error(f"Error fetching role: {e}", exc_info=True)
            raise ServiceError("Could not fetch role. Please try again later.")

    @staticmethod
    def create(data):
        try:
            role = Role(**data)
            db.session.add(role)
            db.session.commit()
            return role
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating role: {e}", exc_info=True)
            raise ServiceError("Could not create role. Please try again later.")

    @staticmethod
    def update(role_id, data):
        try:
            role = Role.query.get(role_id)
            if not role:
                return None
            for key, value in data.items():
                setattr(role, key, value)
            db.session.commit()
            return role
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating role: {e}", exc_info=True)
            raise ServiceError("Could not update role. Please try again later.")

    @staticmethod
    def delete(role_id):
        try:
            role = Role.query.get(role_id)
            if not role:
                return False
            db.session.delete(role)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting role: {e}", exc_info=True)
            raise ServiceError("Could not delete role. Please try again later.") 