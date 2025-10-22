import logging
from backend.extensions import db
from backend.models.driver import Driver
from backend.models.vehicle import Vehicle
from flask_security.utils import verify_password

from datetime import datetime
from decimal import Decimal
from flask import current_app, send_file
from pathlib import Path
from tempfile import NamedTemporaryFile
import os, re, logging
from py_doc_generator.managers import TemplateManager
from py_doc_generator.core.invoice_generator import InvoiceGenerator
from backend.services.contractor_pdf.models import ContractorInvoice, ContractorInvoiceItem, OutputFormat
from backend.models import Job, Contractor
from backend.models.settings import UserSettings
from sqlalchemy.exc import SQLAlchemyError
from backend.models.bill import Bill
from backend.models.driver import Driver

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
        
    @staticmethod
    def driver_invoice_download(bill_id):
        try:
            bill = Bill.query.filter_by(id=bill_id).first()
            if not bill:
                raise ValueError("Driver not found for bill")
            #driver_name = None
            contractor_date = bill.date.date() if hasattr(bill.date, "date") else bill.date
            jobs = bill.jobs
            if not jobs:
                raise ValueError("No jobs found for Driver bill")

            items = []
            total_job_cost = 0.0
            total_cash_collect = 0.0
            for job in jobs:
                job_date = contractor_date
                if hasattr(job_date, "date"):  
                    job_date = job_date.date()

                job_id_str = str(job.id)
                job_cost = float(job.job_cost or 0)
                cash_to_collect = float(job.cash_to_collect or 0)
                driver_id = job.driver_id
                driver_name = Driver.query.filter_by(id=driver_id).first()
                total_job_cost += job_cost
                total_cash_collect += cash_to_collect

                driver_name_str = None
                if isinstance(driver_name, str):
                    driver_name_str = driver_name
                elif driver_name and hasattr(driver_name, "name"):
                    driver_name_str = driver_name.name
                else:
                    driver_name_str = "Unknown"
                items.append(
                ContractorInvoiceItem(
                job_date=job_date,
                job_id=job_id_str,
                driver_name=driver_name_str,
                job_cost=job_cost,
                cash_to_collect=cash_to_collect))

            net_total = total_job_cost - total_cash_collect                
            #driver = Driver.query.filter_by(id=bill.driver_id).first()
            #print("Driver Name:", driver.name)

            user_settings = UserSettings.query.first()
            prefs = user_settings.preferences or {}
            general_settings = prefs.get("general_settings", {})
            company_name = general_settings.get("company_name", "Fleetwise Logistics")

            contractor_invoice = ContractorInvoice(
            company_name=company_name,
            entity_label="Driver",
            contractor_name=driver_name_str,
            bill_no=f"BILL-{bill_id}",
            bill_date=datetime.utcnow().date(),
            items=items,
            total_amount=net_total
            )

            templates_dir = Path(__file__).resolve().parent / "contractor_pdf" /"templates"
            if not templates_dir.exists():
                current_app.logger.error("Doc templates dir not found at %s", templates_dir)
            generator = InvoiceGenerator(templates_dir=str(templates_dir))

            if hasattr(contractor_date, "strftime"):
                contractor_date = contractor_date
            else:
                try:
                    contractor_date = datetime.strptime(str(contractor_date), "%Y-%m-%d")
                except ValueError:
                    current_app.logger.error(f"Invalid Driver invoice date format: {contractor_date}")
                    raise ValueError(f"Invalid Driver invoice date format: {contractor_date}")
            month_str = contractor_date.strftime("%Y-%m")
            if not re.match(r'^\d{4}-\d{2}$', month_str):
                current_app.logger.error(f"Date produced invalid month string: {month_str}")
                raise ValueError(f"Invalid month format: {month_str}")
            
            storage_root_env = current_app.config.get("INVOICE_STORAGE_ROOT")
            if storage_root_env and Path(storage_root_env).exists():
                storage_root = Path(storage_root_env).resolve()
                current_app.logger.info(f"Using configured driver storage root: {storage_root}")
            else:
                # Fallback: derive automatically
                repos_root = Path(current_app.root_path).resolve().parents[2]
                storage_root = repos_root / "fleetwise-storage"
                current_app.logger.warning(
                    f"DRIVER_STORAGE_ROOT not set or invalid. Falling back to: {storage_root}"
                )

            storage_base = storage_root / "driver_invoices"    
            storage_month_dir = storage_base / month_str
            try:
                storage_month_dir.mkdir(parents=True, exist_ok=True)
                if not storage_month_dir.is_dir():
                    raise RuntimeError(f"Storage path exists but is not a directory: {storage_month_dir}")
                if not os.access(storage_month_dir, os.W_OK):
                     raise PermissionError(f"Storage directory is not writable: {storage_month_dir}")
                
            except OSError as e:
                current_app.logger.error(
                f"Cannot create storage directory {storage_month_dir}: {e}"
                )
                raise RuntimeError(f"Failed to create invoice storage: {e}") from e
            pdf_final_path = storage_month_dir / f"{contractor_invoice.bill_no}.pdf"
            temp_pdf = None

            try:
                # Step 1: Write to a temporary file in the same directory (same filesystem)
                with NamedTemporaryFile(dir=storage_month_dir, suffix=".pdf", delete=False) as tmp_file:
                    temp_pdf = Path(tmp_file.name)
                    pdf_result = generator.generate_invoice(
                        invoice=contractor_invoice,
                        template_name="simple_contractor_invoice",
                        output_path=temp_pdf,
                        format_type=OutputFormat.PDF,
                     )

                # Step 2: Validate that PDF generation succeeded
                if not pdf_result.success or not temp_pdf.exists() or temp_pdf.stat().st_size == 0:
                    current_app.logger.error(
                        f"Driver Invoice generation failed for invoice {bill_id}: {getattr(pdf_result, 'error', 'unknown error')}"
                    )
                    raise RuntimeError(f"Driver Invoice generation failed or produced empty file: {temp_pdf}")

                # Step 3: Atomically move the file into place
                os.replace(temp_pdf, pdf_final_path)
                current_app.logger.info(f"Driver Invoice PDF saved atomically: {pdf_final_path}")

            except Exception as e:
                current_app.logger.error(
                    f"Error during PDF generation or atomic save for invoice {bill_id}: {e}", 
                    exc_info=True
                )
            # Cleanup temp file if it exists
            if temp_pdf and temp_pdf.exists():
                try:
                    temp_pdf.unlink()
                    current_app.logger.debug(f"🧹 Cleaned up temp file: {temp_pdf}")
                except Exception as cleanup_err:
                    current_app.logger.warning(f"Failed to delete temp file {temp_pdf}: {cleanup_err}")
                raise

            if not pdf_final_path.exists():
                raise RuntimeError(f"Driver Invoice PDF missing after atomic save: {pdf_final_path}")

            return send_file(
                pdf_final_path,
                mimetype="application/pdf",
                as_attachment=False,            # inline in browser
                download_name=pdf_final_path.name     # Flask 2.0+ (fallbacks automatically if older)
            )

        except FileNotFoundError as e:
            logging.error(f"File not found while generating invoice PDF: {e}", exc_info=True)
            raise FileNotFoundError("Invoice template or resource missing.") from e

        except PermissionError as e:
            logging.error(f"Permission denied during invoice PDF generation: {e}", exc_info=True)
            raise PermissionError("Insufficient permissions to generate invoice PDF.") from e

        except SQLAlchemyError as e:
            logging.error(f"Database error while fetching invoice data: {e}", exc_info=True)
            raise RuntimeError("Could not retrieve invoice data from database.") from e

        except OSError as e:  
            logging.error(f"OS error during invoice PDF generation: {e}", exc_info=True)
            raise RuntimeError("System error occurred while generating invoice PDF.") from e
