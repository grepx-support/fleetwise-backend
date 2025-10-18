import logging
from backend.extensions import db
from backend.models.driver import Driver
from backend.models.vehicle import Vehicle
from flask_security.utils import verify_password

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class DriverService:
    @staticmethod
    def get_all():
        try:
            return Driver.query_active().all()
        except Exception as e:
            logging.error(f"Error fetching drivers: {e}", exc_info=True)
            raise ServiceError("Could not fetch drivers. Please try again later.")

    @staticmethod
    def get_by_id(driver_id):
        try:
            return Driver.query_active().filter_by(id=driver_id).first()
        except Exception as e:
            logging.error(f"Error fetching driver: {e}", exc_info=True)
            raise ServiceError("Could not fetch driver. Please try again later.")

    @staticmethod
    def create(data):
        try:
            driver = Driver(**data)
            db.session.add(driver)
            db.session.commit()
            return driver
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating driver: {e}", exc_info=True)
            raise ServiceError("Could not create driver. Please try again later.")

    @staticmethod
    def update(driver_id, data):
        try:
            # Use filter_by instead of get when using query_active
            driver = Driver.query_active().filter_by(id=driver_id).first()
            if not driver:
                return None
            for key, value in data.items():
                setattr(driver, key, value)
            db.session.commit()
            return driver
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating driver: {e}", exc_info=True)
            raise ServiceError("Could not update driver. Please try again later.")

    @staticmethod
    def delete(driver_id):
        try:
            # Use filter_by instead of get when using query_active
            driver = Driver.query_active().filter_by(id=driver_id).first()
            if not driver:
                return False
            # Soft delete the driver instead of hard delete
            driver.is_deleted = True
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting driver: {e}", exc_info=True)
            raise ServiceError("Could not delete driver. Please try again later.")

    @staticmethod
    def toggle_soft_delete(driver_id, is_deleted):
        try:
            # Get driver including deleted ones for restore functionality
            driver = Driver.query_all().filter_by(id=driver_id).first()
            if not driver:
                return None
            
            driver.is_deleted = is_deleted
            db.session.commit()
            return driver
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error toggling driver soft delete status: {e}", exc_info=True)
            raise ServiceError("Could not update driver status. Please try again later.")

    @staticmethod
    def get_billing_report(driver_id, start_date=None, end_date=None):
        try:
            from backend.models.job import Job
            query = Job.query_active().filter_by(driver_id=driver_id)
            if start_date:
                query = query.filter(Job.pickup_date >= start_date)
            if end_date:
                query = query.filter(Job.pickup_date <= end_date)
            jobs = query.all()
            total_commission = sum(job.driver_commission or 0 for job in jobs)
            total_penalty = sum(job.penalty or 0 for job in jobs)
            job_list = [job.id for job in jobs]
            return {
                'driver_id': driver_id,
                'total_commission': total_commission,
                'total_penalty': total_penalty,
                'jobs': job_list
            }
        except Exception as e:
            logging.error(f"Error generating driver billing report: {e}", exc_info=True)
            raise ServiceError("Could not generate driver billing report. Please try again later.")
        
    @staticmethod
    def getDriverJobs(page,page_size,driver_id):
        try:
            from backend.models.job import Job
            from backend.schemas.job_schema import JobSchema 
            job_schema_many = JobSchema(many=True)

            query = Job.query_active().filter_by(driver_id=driver_id).filter(Job.status.in_(['confirmed', 'otw', 'ots','pob']))
            total = query.count()
            job_list = (
                query.order_by(Job.pickup_date.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                'jobs': job_schema_many.dump(job_list),
                'total':total
            }
        except Exception as e:
            logging.error(f"Error generating driver billing report: {e}", exc_info=True)
            raise ServiceError("Could not get Jobs. Please try again later.")
        
    @staticmethod
    def getDriverCompletedJobs(page,page_size,driver_id):
        try:
            from backend.models.job import Job
            from backend.schemas.job_schema import JobSchema 
            job_schema_many = JobSchema(many=True)

            query = Job.query_active().filter_by(driver_id=driver_id).filter(Job.status.in_(['jc', 'canceled', 'sd']))
            total = query.count()
            job_list = (
                query.order_by(Job.pickup_date.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                'jobs': job_schema_many.dump(job_list),
                'total':total
            }
        except Exception as e:
            logging.error(f"Error generating driver billing report: {e}", exc_info=True)
            raise ServiceError("Could not get Jobs. Please try again later.")

    @staticmethod
    def update_single_job_status(driver_id, job_id, status):
        try:
            from backend.models.job import Job
            job = Job.query_active().filter_by(id=job_id, driver_id=driver_id).first()
            if not job:
                return None
            job.status = status
            db.session.commit()
            return {
                'id': job.id,
                'driver_id': job.driver_id,
                'status': job.status
            }
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating job status for job_id {job_id}, driver_id {driver_id}: {e}", exc_info=True)
            raise ServiceError("Failed to update job status. Please try again later.")
    