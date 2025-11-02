import logging
from backend.extensions import db
from backend.models.contractor import Contractor
from backend.models.contractor_service_pricing import ContractorServicePricing

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
        
    @staticmethod
    def contractor_invoice_download(bill_id):
        try:
            bill = Bill.query.filter_by(id=bill_id).first()
            print("Contractor:", bill.id, bill.contractor_id, bill.driver_id)
            if not bill:
                raise ValueError("Contractor not found for bill")

            contractor_date = bill.date.date() if hasattr(bill.date, "date") else bill.date
            jobs = bill.jobs
            if not jobs:
                raise ValueError("No jobs found for contractor bill")

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

            gross_total = sum(item.job_cost for item in items)        
            contractor = Contractor.query.filter_by(id=bill.contractor_id).first()
            cash_collect_total = sum(item.cash_to_collect for item in items)
            print("Contractor Name:", contractor.name)

            user_settings = UserSettings.query.first()
            prefs = user_settings.preferences or {}
            general_settings = prefs.get("general_settings", {})
            company_name = general_settings.get("company_name", "Fleetwise Logistics")

            contractor_invoice = ContractorInvoice(
            company_name=company_name,
            entity_label="Contractor",
            contractor_name=contractor.name,
            bill_no=f"BILL-{bill_id}",
            bill_date=datetime.utcnow().date(),
            items=items,
            cash_collect_total=round(cash_collect_total, 2),
            total_amount=round(gross_total, 2)
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
                    current_app.logger.error(f"Invalid invoice date format: {contractor_date}")
                    raise ValueError(f"Invalid invoice date format: {contractor_date}")
            month_str = contractor_date.strftime("%Y-%m")
            if not re.match(r'^\d{4}-\d{2}$', month_str):
                current_app.logger.error(f"Date produced invalid month string: {month_str}")
                raise ValueError(f"Invalid month format: {month_str}")
            
            storage_root_env = current_app.config.get("INVOICE_STORAGE_ROOT")
            if storage_root_env and Path(storage_root_env).exists():
                storage_root = Path(storage_root_env).resolve()
                current_app.logger.info(f"Using configured contractor storage root: {storage_root}")
            else:
                # Fallback: derive automatically
                repos_root = Path(current_app.root_path).resolve().parents[2]
                storage_root = repos_root / "fleetwise-storage"
                current_app.logger.warning(
                    f"CONTRACTOR_STORAGE_ROOT not set or invalid. Falling back to: {storage_root}"
                )

            storage_base = storage_root / "contractor_invoices"    
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
            # PDF generation with proper validation (separate concern)
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
                        f"Contractor Invoice generation failed for invoice {bill_id}: {getattr(pdf_result, 'error', 'unknown error')}"
                    )
                    raise RuntimeError(f"Contractor Invoice generation failed or produced empty file: {temp_pdf}")

                # Step 3: Atomically move the file into place
                os.replace(temp_pdf, pdf_final_path)
                temp_pdf = None  # Prevent cleanup in finally block
                current_app.logger.info(f"Contractor Invoice PDF saved atomically: {pdf_final_path}")
            
            except Exception as e:
                current_app.logger.error(
                    f"Error during PDF generation or atomic save for invoice {bill_id}: {e}", 
                    exc_info=True
                )     
                raise
            finally:
                if temp_pdf and temp_pdf.exists():
                    try:
                        temp_pdf.unlink()
                        current_app.logger.debug(f"🧹 Cleaned up temp file: {temp_pdf}")
                    except Exception as cleanup_err:
                        current_app.logger.warning(f"Failed to delete temp file {temp_pdf}: {cleanup_err}")  

            
            if not pdf_final_path.exists():
                raise RuntimeError(f"Contractor Invoice PDF missing after atomic save: {pdf_final_path}")
            
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
