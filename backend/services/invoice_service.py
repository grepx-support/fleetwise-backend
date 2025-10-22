import logging
from backend.extensions import db
from backend.models.invoice import Invoice, Payment
from backend.models.job import Job, JobStatus
from backend.models.customer import Customer
from datetime import datetime, timedelta
import os
import tempfile
import glob
import re
from flask import current_app
from io import BytesIO
from flask import send_file
import os
from sqlalchemy.exc import SQLAlchemyError
from backend.models.vehicle import Vehicle
from backend.models.settings import UserSettings
from backend.models.service import Service
from PIL import Image as PILImage
import yaml
from sqlalchemy.orm import joinedload
from xml.sax.saxutils import escape
import shutil
from datetime import datetime
from tempfile import NamedTemporaryFile

# backend/services/invoice_service.py  
import sys
from pathlib import Path
from datetime import date
from backend.services.invoice_pdf.models.invoice import Invoice as DocInvoice
from backend.services.invoice_pdf.models.invoice_item import InvoiceItem
from backend.services.invoice_pdf.models.output_format import OutputFormat
from py_doc_generator.core.invoice_generator import InvoiceGenerator
from backend.services.invoice_pdf.utils.logo_path import Logo
from decimal import Decimal, ROUND_HALF_UP

# PDF generation imports
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from werkzeug.utils import secure_filename
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.platypus import PageBreak
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class InvoicePDFError(Exception):
    def __init__(self, message: str, invoice_id: str = None):
        super().__init__(message)
        self.invoice_id = invoice_id

def sanitize_filter_value(value):
    """
    Sanitize filter values to prevent SQL injection.
    Only allows alphanumeric characters, spaces, hyphens, underscores, and common punctuation.
    """
    if not value:
        return None

    # Remove any SQL injection attempts
    value = str(value).strip()

    # Check for SQL injection patterns first
    sql_injection_patterns = [
        r'[\'";]',  # Single quotes, double quotes, semicolons
        r'--',  # SQL comments
        r'/\*',  # SQL block comments
        r'\*/',  # SQL block comments
        r'xp_cmdshell',  # SQL Server command shell
        r'WAITFOR',  # SQL Server wait
        r'SHUTDOWN',  # SQL Server shutdown
        r'DROP\s+TABLE',  # DROP TABLE
        r'DELETE\s+FROM',  # DELETE FROM
        r'INSERT\s+INTO',  # INSERT INTO
        r'UPDATE\s+SET',  # UPDATE SET
        r'UNION\s+SELECT',  # UNION SELECT
        r'EXEC\s+',  # EXEC
        r'EXECUTE\s+',  # EXECUTE
    ]

    for pattern in sql_injection_patterns:
        if re.search(pattern, value, re.IGNORECASE):
            logging.warning(f"SQL injection pattern detected: {pattern} in value: {value}")
            return None

    # Only allow safe characters for search
    # Allow alphanumeric, spaces, hyphens, underscores, dots, and limited punctuation
    safe_pattern = re.compile(r'^[a-zA-Z0-9\s\-_.,:!?@#$%&*()+=<>[\]{}|\\/"`~]+$')

    if not safe_pattern.match(value):
        logging.warning(f"Potentially unsafe filter value detected: {value}")
        return None

    return value

class InvoiceService:
    @staticmethod
    def get_all():
        try:
            return Invoice.query.all()
        except Exception as e:
            logging.error(f"Error fetching invoices: {e}", exc_info=True)
            raise ServiceError("Could not fetch invoices. Please try again later.")

    @staticmethod
    def get_by_id(invoice_id):
        try:
            return Invoice.query.get(invoice_id)
        except Exception as e:
            logging.error(f"Error fetching invoice: {e}", exc_info=True)
            raise ServiceError("Could not fetch invoice. Please try again later.")

    @staticmethod
    def create(data):
        try:
            invoice = Invoice(**data)
            db.session.add(invoice)
            db.session.commit()
            return invoice
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error creating invoice: {e}", exc_info=True)
            raise ServiceError("Could not create invoice. Please try again later.")

    @staticmethod
    def generate_invoice_for_jobs(job_ids, customer_id):
        try:
            # Use optimized loading for invoice generation - only need basic job data
            jobs = Job.query.filter(Job.id.in_(job_ids), Job.is_deleted.is_(False)).all()
            if not jobs:
                return {'error': 'No jobs found for the provided job IDs.'}

            customer_ids = {job.customer_id for job in jobs}
            if len(customer_ids) > 1:
                raise ServiceError("All jobs must belong to the same customer")
            if customer_id not in customer_ids:
                return {'error': 'Provided customer_id does not match job data.'}

            total_amount = sum(job.final_price or 0 for job in jobs)
            invoice = Invoice(
                customer_id=customer_id,
                date=datetime.utcnow(),
                status='Unpaid',
                total_amount=total_amount
            )
            db.session.add(invoice)
            db.session.flush()
            for job in jobs:
                job.invoice_id = invoice.id
            db.session.commit()
            breakdown = [{'job_id': job.id, 'final_price': job.final_price} for job in jobs]
            return {
                'invoice_id': invoice.id,
                'total_amount': total_amount,
                'breakdown': breakdown
            }
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error generating invoice: {e}", exc_info=True)
            raise ServiceError("Could not generate invoice. Please try again later.")

    @staticmethod
    def get_billing_report(customer_id=None, start_date=None, end_date=None, status=None):
        try:
            query = Invoice.query
            if customer_id:
                query = query.filter_by(customer_id=customer_id)
            if status:
                query = query.filter_by(status=status)
            if start_date:
                query = query.filter(Invoice.date >= start_date)
            if end_date:
                query = query.filter(Invoice.date <= end_date)
            invoices = query.all()
            total_amount = sum(inv.total_amount or 0 for inv in invoices)
            summary = {
                'count': len(invoices),
                'total_amount': total_amount
            }
            return {
                'summary': summary,
                'invoices': [inv.id for inv in invoices]
            }
        except Exception as e:
            logging.error(f"Error generating billing report: {e}", exc_info=True)
            raise ServiceError("Could not generate billing report. Please try again later.")

    @staticmethod
    def invoices_with_jobs_by_status(page, page_size, status, customer_name, service_type):
        try:
            invoice_query = Invoice.query

            if status:
                invoice_query = invoice_query.filter(Invoice.status == status)

            invoice_query = invoice_query.order_by(Invoice.date.desc())
            pagination = invoice_query.paginate(page=page, per_page=page_size, error_out=False)
            invoices = pagination.items
            total = pagination.total
            invoice_data = []
            for invoice in invoices:
                jobs_query = Job.query.filter(
                    Job.invoice_id == invoice.id,
                    Job.status == JobStatus.JC.value,
                    Job.is_deleted.is_(False)
                )
                if customer_name:
                    pattern = '%' + sanitize_filter_value(customer_name) + '%'
                    jobs_query = jobs_query.join(Job.customer).filter(Customer.name.ilike(pattern))

                if service_type:
                    pattern = '%' + sanitize_filter_value(service_type) + '%'
                    jobs_query = jobs_query.filter(Job.service_type.ilike(pattern))

                invoice_jobs = jobs_query.all()
                invoice.jobs = invoice_jobs
                invoice_data.append(invoice)
            return {
                'total': total,
                'invoices': invoice_data
            }
        except SQLAlchemyError as e:
                logging.error(f"Database error querying jobs: {e}", exc_info=True)
                raise ServiceError("Failed to fetch invoice jobs")
        except ValueError as e:
                logging.error(f"Validation error in jobs query: {e}", exc_info=True)
                raise ServiceError(f"Invalid data format: {str(e)}")
        except Exception as e:
            logging.error(f"Error fetching invoice jobs: {e}", exc_info=True)
            raise ServiceError("Could not fetch invoice jobs. Please try again later.")
    @staticmethod
    def remove_invoice(invoice_id):
        try:
            invoice = Invoice.query.get(invoice_id)
            if not invoice:
                return {'error': 'Invoice not found'}
            jobs = Job.query.filter(Job.invoice_id == invoice_id, Job.is_deleted.is_(False)).all()
            for job in jobs:
                job.invoice_id = None
            db.session.delete(invoice)
            db.session.commit()
            return {'success': True, 'message': 'Invoice deleted and jobs updated'}
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error removing invoice and unlinking jobs: {e}", exc_info=True)
            raise ServiceError("Could not remove invoice. Please try again later.")

    @staticmethod
    def delete(invoice_id):
        try:
            invoice = Invoice.query.get(invoice_id)
            if not invoice:
                return False
            db.session.delete(invoice)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error deleting invoice: {e}", exc_info=True)
            raise ServiceError("Could not delete invoice. Please try again later.")

    @staticmethod
    def update(invoice_id, data):
        try:
            invoice = Invoice.query.get(invoice_id)
            if not invoice:
                return None
            for key, value in data.items():
                setattr(invoice, key, value)
            db.session.commit()
            return invoice
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating invoice: {e}", exc_info=True)
            raise ServiceError("Could not update invoice. Please try again later.")

    @staticmethod
    def update_status(invoice_id, data):
        try:
            invoice = Invoice.query.get(invoice_id)
            if not invoice:
                return None

            old_status = invoice.status

            for key, value in data.items():
                setattr(invoice, key, value)

            if data.get('status') == 'Paid' and old_status != 'Paid':
                try:
                    InvoiceService.generate_invoice_pdf(invoice)
                except Exception as pdf_err:
                    logging.error(f"PDF generation failed: {pdf_err}", exc_info=True)
            db.session.commit()
            return invoice
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error updating invoice: {e}", exc_info=True)
            raise Exception("Could not update invoice. Please try again later.")

    @staticmethod
    def generate_invoice_pdf(invoice):
        """Generate a PDF for the invoice and update file_path and total_amount"""
        if not PDF_AVAILABLE:
            logging.error("PDF generation not available. Install PDF dependencies: pip install -r requirements-pdf.txt")
            raise ServiceError("PDF generation is not available. Please install PDF dependencies with: pip install -r requirements-pdf.txt.")

        jobs = Job.query.filter(Job.invoice_id == invoice.id, Job.is_deleted.is_(False)).all()
        total = 0
        
        output_folder = os.path.join(current_app.root_path, 'billing_invoices')
        os.makedirs(output_folder, exist_ok=True)

        filename = f"invoice_{invoice.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(output_folder, filename)

        # Create the PDF document
        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=20,
            alignment=1  # Center alignment
        )
        title = Paragraph("Fleet Wise Services Pte Ltd - INVOICE", title_style)
        story.append(title)
        story.append(Spacer(1, 20))

        # Invoice details
        invoice_info = [
            f"Invoice No: {invoice.id}",
            f"Date: {datetime.utcnow().strftime('%d-%b-%Y')}"
        ]
        for info in invoice_info:
            story.append(Paragraph(info, styles['Normal']))
        story.append(Spacer(1, 20))

        # Table data
        table_data = [['Date', 'Time', 'Service Type', 'Route', 'Passenger', 'Amount (SGD)']]
        
        for job in jobs:
            total += job.final_price
            passenger_info = f"{job.passenger_name or '-'}"
            if job.passenger_mobile:
                passenger_info += f"<br/>{job.passenger_mobile}"
            
            table_data.append([
                str(job.pickup_date),
                job.pickup_time or '-',
                job.service_type,
                f"{job.pickup_location} → {job.dropoff_location}",
                passenger_info,
                f"${job.final_price:.2f}"
            ])

        # Add total row
        table_data.append(['', '', '', '', 'Total', f"${total:.2f}"])

        # Create table
        table = Table(table_data, colWidths=[1*inch, 0.8*inch, 1.2*inch, 2*inch, 1.5*inch, 1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#20A7DB")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
            # ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),  # Right align amounts
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),  # Total row
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 30))

        # Footer information
        footer_text = """
        This is a computer-generated invoice. No signature is required.<br/><br/>
        Kindly arrange cheques payable to "Avant-garde Services Pte Ltd" and cross "A/C Payee Only".<br/>
        <strong>Bank:</strong> UOB (7375) - A/C: 3733169263 - SWIFT: UOVBSGSG<br/>
        <strong>PayNow:</strong> 201017519Z<br/>
        <strong>Contact:</strong> 8028 6168 | <strong>Email:</strong> joey@avant-garde.com.sg
        """
        story.append(Paragraph(footer_text, styles['Normal']))

        # Build PDF
        doc.build(story)
        
        invoice.file_path = f"/billing_invoices/{filename}"
        invoice.total_amount = total
        db.session.commit()
        logging.info(f"Invoice PDF created at: {pdf_path}")
        InvoiceService.cleanup_old_pdfs(output_folder)

    @staticmethod
    def cleanup_old_pdfs(pdf_dir):
        cutoff = datetime.now() - timedelta(days=30)
        try:
            for file_path in glob.glob(os.path.join(pdf_dir, '*.pdf')):
                if os.path.isfile(file_path) and os.path.getctime(file_path) < cutoff.timestamp():
                    os.remove(file_path)
                    logging.info(f"Old invoice PDF deleted: {file_path}")
        except Exception as e:
            logging.error(f"Error during PDF cleanup: {e}")

   
    @staticmethod
    def build_particulars(job):
        pickups = [
        job.pickup_location,
        getattr(job, "pickup_loc1", None),
        getattr(job, "pickup_loc2", None),
        getattr(job, "pickup_loc3", None),
        getattr(job, "pickup_loc4", None),
        getattr(job, "pickup_loc5", None),
    ]
        dropoffs = [
        job.dropoff_location,
        getattr(job, "dropoff_loc1", None),
        getattr(job, "dropoff_loc2", None),
        getattr(job, "dropoff_loc3", None),
        getattr(job, "dropoff_loc4", None),
        getattr(job, "dropoff_loc5", None),
    ]
        lines = []
        if pickups[0]:
            lines.append(f"ⓟ{pickups[0]}")
        for i, loc in enumerate(pickups[1:], start=1):
            if loc:
                lines.append(f"<span style='font-size: 13px; color:#444;'> > {loc} (Stop {i})</span>")
        if dropoffs[0]:
            lines.append(f"Ⓓ {dropoffs[0]}")
        for loc in dropoffs[1:]:
            if loc:
                lines.append(f"<span style='font-size: 13px; color:#444;'> • {loc}</span>")
        return "<br>".join(lines)


    def unpaid_invoice_download(invoice_id):
        
        if not isinstance(invoice_id, int) or invoice_id <= 0:
            raise ValueError(f"Invalid invoice_id: {invoice_id}")
        try:
            from py_doc_generator.managers import TemplateManager
            invoice = Invoice.query.get(invoice_id)
            customer = Customer.query.get(invoice.customer_id)
            jobs = Job.query.filter_by(invoice_id=invoice_id).all()

            service_names = [job.service_type for job in jobs if job.service_type]
            services = Service.query.filter(Service.name.in_(service_names)).all()
            service_map = {s.name: s for s in services}
        
            # Build items for py-doc-generator
            items = []
            for job in jobs:
                service = service_map.get(job.service_type)
                items.append(InvoiceItem(
                Date=job.pickup_date,
                Time=job.pickup_time,
                Job= f"#{job.id}",
                Particulars=InvoiceService.build_particulars(job),
                ServiceType=service.name if service else job.service_type,
                amount=f"{job.final_price:.2f}",
                ))
        
            user_settings = UserSettings.query.first()
            prefs = user_settings.preferences or {} if user_settings else {}
            billing_settings = prefs.get("billing_settings", {})
            company_logo = billing_settings.get("company_logo", "")
            logo_path = Logo.safe_logo_path(company_logo)

            # GST
            raw_gst = billing_settings.get("gst_percent", 0) or 0
            gst_percent = Decimal(str(raw_gst))  

            sub_total = Decimal(str(invoice.total_amount))
            gst_amount = (sub_total * gst_percent / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            grand_total = (sub_total + gst_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            # Footer Data
            general_settings = prefs.get("general_settings", {})
            company_address = general_settings.get("company_address", "")
            email = general_settings.get("email_id", "")
            contact_number = general_settings.get("contact_number", "")

            # Payment Info and QR Code
            payment_info = billing_settings.get("billing_payment_info", "")
            qr_path = Logo.safe_logo_path(billing_settings.get("billing_qr_code_image", ""))

            # Build the py-doc-generator Invoice object

            doc_invoice = DocInvoice(
            number=f"INV-{invoice.id}",
            date=(invoice.date.date() if hasattr(invoice.date, "date") else invoice.date),
            from_company=customer.name,
            from_email=customer.email,
            from_mobile=customer.mobile,
            to_company=customer.name,
            to_address=customer.address or "",
            items=items,
            notes="Thank you for your business!",
            currency="SGD",
            logo_path=logo_path,
            sub_total=sub_total,
            gst_amount=gst_amount,
            total_amount=grand_total,
            company_address= company_address,
            email=email,
            contact_number=contact_number,
            payment_info=payment_info,
            qr_code=qr_path
            )

            templates_dir = Path(__file__).resolve().parent / "invoice_pdf" / "templates"
            if not templates_dir.exists():
                current_app.logger.error("Doc templates dir not found at %s", templates_dir)
            modern_dir = templates_dir / "modern_invoice"

            if not modern_dir.exists():
                current_app.logger.error("Template 'modern_invoice' not found at: %s", modern_dir)
                raise FileNotFoundError("Invoice template 'modern_invoice' not found")

            generator = InvoiceGenerator(templates_dir=str(templates_dir))

            # === Save a copy in fleetwise-storage organized by invoice.date month ===
            if hasattr(invoice.date, "strftime"):
                invoice_date = invoice.date
            else:
                try:
                    invoice_date = datetime.strptime(str(invoice.date), "%Y-%m-%d")
                except ValueError:
                    current_app.logger.error(f"Invalid invoice date format: {invoice.date}")
                    raise ValueError(f"Invalid invoice date format: {invoice.date}")
            month_str = invoice_date.strftime("%Y-%m")
            if not re.match(r'^\d{4}-\d{2}$', month_str):
                current_app.logger.error(f"Date produced invalid month string: {month_str}")
                raise ValueError(f"Invalid month format: {month_str}")

            # --- Determine storage root ---
            storage_root_env = current_app.config.get("INVOICE_STORAGE_ROOT")
            if storage_root_env and Path(storage_root_env).exists():
                storage_root = Path(storage_root_env).resolve()
                current_app.logger.info(f"Using configured invoice storage root: {storage_root}")
            else:
                # Fallback: derive automatically
                repos_root = Path(current_app.root_path).resolve().parents[2]
                storage_root = repos_root / "fleetwise-storage"
                current_app.logger.warning(
                    f"INVOICE_STORAGE_ROOT not set or invalid. Falling back to: {storage_root}"
                )

            storage_base = storage_root / "invoices"    
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

            pdf_final_path = storage_month_dir / f"{doc_invoice.number}.pdf"
            temp_pdf = None

            try:
                # Step 1: Write to a temporary file in the same directory (same filesystem)
                with NamedTemporaryFile(dir=storage_month_dir, suffix=".pdf", delete=False) as tmp_file:
                    temp_pdf = Path(tmp_file.name)
                    pdf_result = generator.generate_invoice(
                        invoice=doc_invoice,
                        template_name="modern_invoice",
                        output_path=temp_pdf,
                        format_type=OutputFormat.PDF,
                     )

                # Step 2: Validate that PDF generation succeeded
                if not pdf_result.success or not temp_pdf.exists() or temp_pdf.stat().st_size == 0:
                    current_app.logger.error(
                        f"Invoice generation failed for invoice {invoice_id}: {getattr(pdf_result, 'error', 'unknown error')}"
                    )
                    raise RuntimeError(f"Invoice generation failed or produced empty file: {temp_pdf}")

                # Step 3: Atomically move the file into place
                os.replace(temp_pdf, pdf_final_path)
                current_app.logger.info(f"✅ Invoice PDF saved atomically: {pdf_final_path}")

            except Exception as e:
                current_app.logger.error(
                    f"Error during PDF generation or atomic save for invoice {invoice_id}: {e}", 
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
                raise RuntimeError(f"Invoice PDF missing after atomic save: {pdf_final_path}")

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

        except KeyError as e:
            logging.error("Missing required invoice field: %s", e, exc_info=True)
            raise InvoicePDFError(f"Invoice data is incomplete (missing {e}).") from e

        except ValueError as e:
            logging.error("Invalid data value: %s", e, exc_info=True)
            raise InvoicePDFError("Invoice data contained invalid values.") from e
   
        except Exception as e:
            logging.critical("Unexpected error in invoice PDF generation: %s", e, exc_info=True)
            raise InvoicePDFError("Unexpected error occurred while generating invoice PDF.") from e


class PaymentService:
    @staticmethod
    def generate_payment_receipt(invoice_id):
        """Generate a PDF for an invoice showing all payments (partial/full)."""
        if not PDF_AVAILABLE:
            raise ServiceError("PDF generation is not available. Please install PDF dependencies.")
        invoice_data = Invoice.query.get(invoice_id)
        pdf_io = BytesIO()
        doc = SimpleDocTemplate(pdf_io, pagesize=A4,
                                rightMargin=40, leftMargin=40,
                                topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        story = []

        # --- Header: Logo + Invoice Info ---
        logo_path = os.path.join(current_app.root_path, "static", "images", "fleetwise.png")
        logo = Image(logo_path, width=200, height=60)

        # customer_name = invoice_data.get("customer_name", "Customer Name")
        customer = Customer.query.get(invoice_data.customer_id)
        # customer_info = Paragraph(f"""
        # <b>{customer.name}</b><br/>
        # """, styles['Normal'])
        
        payments = Payment.query.filter_by(invoice_id=invoice_id).first()
        client_info = Paragraph("""
            <b>Sea Wheel Travel Pte Ltd</b><br/>
            101 Upper Cross Street<br/>
            #06-09/10 People's Park Centre<br/>
            Singapore 058357<br/>
            Attn: Mr Jeff Goh
            """, styles["Normal"])

        payment_date = payments.date.strftime('%d-%b-%Y   %H:%M') if payments and payments.date else datetime.utcnow().strftime('%d-%b-%Y   %H:%M')
        invoice_info = Paragraph(f"""
        <b>INVOICE</b><br/>
        <b>Customer:</b> {customer.name}<br/>
        <b>Date:</b> {payment_date}<br/>
        <b>Inv. No.:</b> {invoice_data.id}<br/>
        <b>Status:</b> {invoice_data.status}<br/>
       <b> Total Amount: </b>{invoice_data.total_amount:.2f}<br/>
        <b>Remaining Amount:</b> {invoice_data.remaining_amount:.2f}
        """, styles['Normal'])

        header_table = Table([[logo, ''], [client_info, invoice_info]], colWidths=[300, 200])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 1), (1, 1), 'RIGHT'),
            ('BOTTOMPADDING', (0, 0), (0, 0), 8),
            ('LEFTPADDING', (0, 0), (0, 0), -10),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 20))

        # --- Payments Table ---
        payments_all = Payment.query.filter_by(invoice_id=invoice_data.id).order_by(Payment.date.asc()).all()

        if payments_all:
            story.append(Paragraph("<b> Payments Received </b>", styles['Heading2']))
            story.append(Spacer(1, 10))

            payment_table_data = [['Date', 'Amount (SGD)', 'Notes', 'Cumulative Paid', 'Remaining Balance']]
            cumulative_paid = 0
            total_amount = invoice_data.total_amount

            for p in payments_all:
                amt = p.amount
                cumulative_paid += amt
                note_paragraph = Paragraph(p.notes or '-', styles['Normal'])
                payment_table_data.append([
                    p.date.strftime('%d-%b-%Y %H:%M'),  # format datetime
                    f"{amt:.2f}",
                    note_paragraph,
                    f"{cumulative_paid:.2f}",
                    f"{total_amount - cumulative_paid:.2f}"
                ])

            #col_widths = [1.5*inch, 1*inch, 2.5*inch, 1.2*inch, 1.2*inch]
            available_width = A4[0] - 80 
            col_widths = [
            0.20 * available_width,  
            0.18 * available_width, 
            0.25 * available_width,  
            0.17 * available_width,  
            0.20 * available_width  
             ]
            payment_table = Table(payment_table_data, col_widths)
            payment_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#20A7DB")),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                # ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('ALIGN', (-2,1), (-1,-1), 'RIGHT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),  
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),  
                ('TOPPADDING', (0, 0), (-1, -1), 3),   
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(payment_table)
            story.append(Spacer(1, 20))

        # --- Footer ---
        footer_text = """
            This is a computer generated document, no signature is required.<br/><br/>
            Kindly arrange all cheques to be made payable to <b>"Avant-Garde Services Pte Ltd"</b> and crossed <b>"A/C Payee Only"</b>.<br/>
            Alternatively, for Bank Transfer / Electronic Payment please find our bank details as follows:<br/>
            <b>UOB Bank (7375)</b> : Current A/C : 3733169263 / Bank Swift Code : UOVBSGSG<br/>
            <b>Corporate Paynow</b> : 201017519Z<br/>
            Hp : 8028 6168 | Email : joey@avant-garde.com.sg<br/><br/>
            160 Sin Ming Drive #05-09 Sin Ming AutoCity (S)575722<br/>
            Tel : 6316 8168 | <u>www.avant-garde.com.sg</u>
            """
        story.append(Paragraph(footer_text, styles['Normal']))

        # Build PDF
        doc.build(story)
        pdf_io.seek(0)

        return send_file(
            pdf_io,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'invoice_{invoice_data.id}.pdf'
        )
