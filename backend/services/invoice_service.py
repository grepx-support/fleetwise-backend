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
from backend.services.invoice_pdf.utils.logo_path import Logo
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

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
    # Define fallbacks to prevent undefined variable errors
    from typing import Any
    SimpleDocTemplate = None
    getSampleStyleSheet = None
    ParagraphStyle = None
    Paragraph = None
    Spacer = None
    Table = None
    TableStyle = None
    colors = None

# WeasyPrint imports for PDF generation
try:
    # Add the py-doc-generator to the path
    import sys
    import os
    py_doc_generator_path = os.path.join(os.path.dirname(__file__), '..', 'libs', 'py-doc-generator')
    if py_doc_generator_path not in sys.path:
        sys.path.append(py_doc_generator_path)
    from py_doc_generator.core.invoice_generator import InvoiceGenerator  # type: ignore
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    InvoiceGenerator = None

logger = logging.getLogger(__name__)

class ServiceError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

class InvoicePDFError(Exception):
    def __init__(self, message: str, invoice_id = None):
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
    def _get_gst_percent(billing_settings: dict) -> Decimal:
        """Extract and validate GST percentage from billing settings."""
        raw_gst = billing_settings.get("gst_percent")
        if raw_gst is None:
            return Decimal("0")

        try:
            gst_percent = Decimal(str(raw_gst))
            if gst_percent < 0 or gst_percent > 100:
                logger.warning(f"Invalid GST percent {gst_percent}, using 0")
                return Decimal("0")
            return gst_percent
        except (ValueError, InvalidOperation) as e:
            logger.error(f"Failed to parse GST percent '{raw_gst}': {e}")
            return Decimal("0")


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

            
            #total_amount = sum(job.final_price or 0 for job in jobs)
            sub_total = sum(Decimal(str(job.final_price or 0)) for job in jobs)
            sub_total = sub_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # determine gst_percent from billing settings (fallback to 0 or desired default)
            try:
                user_settings = UserSettings.query.first()
                prefs = user_settings.preferences or {} if user_settings else {}
            except Exception as e:
                logger.error(f"Failed to fetch UserSettings: {e}")
                prefs = {}
            billing_settings = prefs.get("billing_settings", {}) if prefs else {}
            gst_percent = InvoiceService._get_gst_percent(billing_settings)

            # calculate gst_amount and grand_total
            cash = sum(Decimal(str(job.cash_to_collect or 0)) for job in jobs)
            gst_amount = (sub_total * gst_percent / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            grand_total = (sub_total + gst_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            invoice = Invoice(
                customer_id=customer_id,
                date=datetime.utcnow(),
                status='Unpaid',
                total_amount=float(grand_total) if not isinstance(Invoice.total_amount, property) else grand_total,
                remaining_amount_invoice=float(grand_total - cash),
            )
            db.session.add(invoice)
            db.session.flush()
            if cash > 0:
                job_ids_with_cash = [str(job.id) for job in jobs if job.cash_to_collect and job.cash_to_collect > 0]
                payment = Payment(
                invoice_id=invoice.id,
                amount=float(cash.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                date=datetime.utcnow(),
                notes=f"Cash collected from jobs: {', '.join(job_ids_with_cash)}"
                )
                db.session.add(payment)
            for job in jobs:
                job.invoice_id = invoice.id
            db.session.commit()
            breakdown = [{'job_id': job.id, 'final_price': job.final_price} for job in jobs]
            return {
                'invoice_id': invoice.id,
                'total_amount': str(grand_total),
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
                    sanitized_name = sanitize_filter_value(customer_name)
                    if sanitized_name:
                        pattern = '%' + sanitized_name + '%'
                        jobs_query = jobs_query.join(Customer, Job.customer_id == Customer.id).filter(Customer.name.ilike(pattern))

                if service_type:
                    sanitized_service = sanitize_filter_value(service_type)
                    if sanitized_service:
                        pattern = '%' + sanitized_service + '%'
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
            try:
                user_settings = UserSettings.query.first()
                prefs = user_settings.preferences or {} if user_settings else {}
            except Exception as e:
                logger.error(f"Failed to fetch UserSettings: {e}")
                prefs = {}
            billing_settings = prefs.get("billing_settings", {})

            gst_percent = InvoiceService._get_gst_percent(billing_settings)
            # gst_multiplier = float(1 + gst_percent / Decimal("100"))

            jobs = Job.query.filter(Job.invoice_id == invoice_id, Job.is_deleted.is_(False)).all()
            for job in jobs:
                job.invoice_id = None
                if job.final_price:
                    job.final_price = float(
                        Decimal(str(job.final_price))
                        )
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
    def generate_invoice_pdf_reportlab(invoice):
        """Generate a PDF for the invoice using ReportLab (fallback method)"""
        if not PDF_AVAILABLE:
            logging.error("PDF generation not available. Install PDF dependencies: pip install -r requirements-pdf.txt")
            raise ServiceError("PDF generation is not available. Please install PDF dependencies with: pip install -r requirements-pdf.txt.")

        # Load jobs with vehicle_type relationship eagerly loaded
        jobs = Job.query.options(db.joinedload(Job.vehicle_type)).filter(Job.invoice_id == invoice.id, Job.is_deleted.is_(False)).all()

        # Validate jobs first - fail fast with clear errors
        invalid_jobs = []
        for job in jobs:
            missing = []
            if not job.pickup_date:
                missing.append('pickup_date')
            if not job.pickup_time:
                missing.append('pickup_time')
            if not job.service_type:
                missing.append('service_type')
            if job.final_price is None:
                missing.append('final_price')
            if missing:
                invalid_jobs.append(f"Job #{job.id}: missing {', '.join(missing)}")

        if invalid_jobs:
            error_msg = f"Cannot generate invoice {invoice.id}: " + "; ".join(invalid_jobs)
            logging.error(error_msg)
            raise ValueError(error_msg)

        output_folder = os.path.join(current_app.root_path, 'billing_invoices')
        os.makedirs(output_folder, exist_ok=True)

        filename = f"invoice_{invoice.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_path = os.path.join(output_folder, filename)

        # Create the PDF document
        doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=72, bottomMargin=72)
        styles = getSampleStyleSheet()
        story = []

        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=14,
            spaceAfter=20,
            alignment=1,  # Center alignment
            fontName='Helvetica-Bold'
        )
        
        normal_style = ParagraphStyle(
            'Normal',
            parent=styles['Normal'],
            fontSize=10,
            fontName='Helvetica'
        )
        
        right_style = ParagraphStyle(
            'Right',
            parent=normal_style,
            alignment=2  # Right alignment
        )

        # Get QR code path from user settings
        user_settings = UserSettings.query.first()
        prefs = user_settings.preferences or {} if user_settings else {}
        billing_settings = prefs.get("billing_settings", {})
        qr_path = Logo.safe_logo_path(billing_settings.get("billing_qr_code_image", ""))
        company_logo = billing_settings.get("company_logo", "")
        logo_path = Logo.safe_logo_path(company_logo)
        
        # Header - Company info and Invoice info
        header_content = []
        
        # Create a single row with company info (logo + name) on left and INVOICE on right
        company_cell_content = []
        
        # Add company logo if available
        if logo_path and os.path.exists(logo_path):
            try:
                # Add logo image
                logo_image = Image(logo_path, width=100, height=30)  # Adjust size to match requirements
                company_cell_content.append(logo_image)
            except:
                # Fallback to text if logo fails to load
                company_cell_content.append(Paragraph("<b>AVANT-GARDE SERVICES PTE LTD</b>", normal_style))
        else:
            # Fallback to text if no logo or logo doesn't exist
            company_cell_content.append(Paragraph("<b>AVANT-GARDE SERVICES PTE LTD</b>", normal_style))
            
        header_content.append([company_cell_content, Paragraph("<b>INVOICE</b>", normal_style)])
        
        header_table = Table(header_content, colWidths=[4*inch, 2*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 14),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 12))

        # Customer and invoice details
        customer = Customer.query.get(invoice.customer_id)
        
        # Build customer contact info
        customer_contact = ""
        if customer.mobile:
            customer_contact = customer.mobile
        elif customer.email:
            customer_contact = customer.email
        
        customer_info = [
            Paragraph(f"<b>{customer.name}</b>", normal_style),
            Paragraph(customer.address or "", normal_style),
        ]
        
        # Add customer contact if available
        if customer_contact:
            customer_info.append(Paragraph(customer_contact, normal_style))
        
        invoice_info = [
            Paragraph(f"Date : {datetime.utcnow().strftime('%d-%b-%Y')}", right_style),
            Paragraph("Term : 14 Days", right_style),
            Paragraph(f"Inv. No : {invoice.id}", right_style),
        ]
        
        details_table = Table([[customer_info, invoice_info]], colWidths=[4*inch, 2*inch])
        details_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(details_table)
        story.append(Spacer(1, 20))

        # Calculate totals - always recompute from jobs for accuracy
        computed_total = sum(Decimal(str(job.final_price or 0)) for job in jobs)
        sub_total = computed_total

        # Log discrepancies for audit
        if invoice.total_amount is not None:
            stored = Decimal(str(invoice.total_amount))
            if abs(stored - computed_total) > Decimal("0.01"):
                logging.warning(
                    f"Invoice {invoice.id} total mismatch: stored={stored}, "
                    f"computed={computed_total}. Using computed."
                )
        gst_amount = sub_total * Decimal("0.09")  # 9% GST
        gst_amount = gst_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_amount = sub_total + gst_amount
        cash_collect_total = sum(job.cash_to_collect or 0 for job in jobs)
        # Ensure cash_collect_total is a Decimal
        if not isinstance(cash_collect_total, Decimal):
            cash_collect_total = Decimal(str(cash_collect_total))

        # Table data
        table_data = [['Date & Time', 'Cust Ref', 'Job ID', 'Particulars', 'Vehicle Type', 'Cash Collected', 'Amount']]
        
        for job in jobs:
            # Get vehicle type name from job's vehicle_type relationship
            vehicle_type_name = ""
            if hasattr(job, 'vehicle_type') and job.vehicle_type:
                vehicle_type_name = job.vehicle_type.name
            elif hasattr(job, 'vehicle_type_id') and job.vehicle_type_id:
                # If we have vehicle_type_id but not the relationship, we can fetch it
                from backend.models.vehicle_type import VehicleType
                vehicle_type = VehicleType.query.get(job.vehicle_type_id)
                if vehicle_type:
                    vehicle_type_name = vehicle_type.name
            
            # Get customer reference from booking_ref field
            customer_reference = getattr(job, 'booking_ref', '') or ''

            # Get service name
            service_name = job.service_type or ''

            # Build particulars with service name
            particulars = InvoiceService.build_particulars(job, service_name)

            table_data.append([
                f"{job.pickup_date} {job.pickup_time or '-'}",
                customer_reference,
                f"#{job.id}",
                particulars,
                vehicle_type_name,
                f"{float(job.cash_to_collect or 0):.2f}",
                f"{float(job.final_price or 0):.2f}"
            ])

        # Create table with adjusted column widths
        table = Table(table_data, colWidths=[1.2*inch, 1.0*inch, 0.8*inch, 2.0*inch, 1.2*inch, 1.1*inch, 1.1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0056b3")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 10),  # Ensure body font size is also 10pt
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),  # Light gray borders
            ('ALIGN', (5, 0), (6, -1), 'RIGHT'),  # Right align cash collected and amount columns
            # Alternating row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ]))
        # Enable table header repetition on new pages
        table.repeatRows = 1
        story.append(table)
        story.append(Spacer(1, 30))

        # Totals section
        balance_amount = total_amount - cash_collect_total
        totals_data = [
            [Paragraph("Sub Total", normal_style), Paragraph(f"{sub_total:.2f}", right_style)],
            [Paragraph("", normal_style), Paragraph("", right_style)],  # Spacer row
            [Paragraph("GST (9%)", normal_style), Paragraph(f"{gst_amount:.2f}", right_style)],
            [Paragraph("", normal_style), Paragraph("", right_style)],  # Spacer row
            [Paragraph("Total Amount", normal_style), Paragraph(f"{total_amount:.2f}", right_style)],
            [Paragraph("Cash Collected", normal_style), Paragraph(f"{cash_collect_total:.2f}", right_style)],
            [Paragraph("", normal_style), Paragraph("", right_style)],  # Spacer row
            [Paragraph("<b>Balance Amount</b>", normal_style), Paragraph(f"<b>{balance_amount:.2f}</b>", right_style)],
        ]
        
        totals_table = Table(totals_data, colWidths=[2*inch, 1.5*inch])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -2), 'Helvetica'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            # Lines
            ('LINEBELOW', (0, 0), (1, 0), 0.5, colors.black),  # Sub Total line
            ('LINEBELOW', (0, 2), (1, 2), 0.5, colors.black),  # GST line
            ('LINEBELOW', (0, 4), (1, 4), 0.5, colors.black),  # Total Amount line
            ('LINEBELOW', (0, 6), (1, 6), 1, colors.black),    # Balance Amount line (thicker)
        ]))
        
        # Wrap totals in a right-aligned table
        totals_wrapper = Table([[totals_table]], colWidths=[None, 3.5*inch])
        totals_wrapper.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ]))
        story.append(totals_wrapper)
        story.append(Spacer(1, 20))

        # Footer information
        footer_text = """
        Kindly arrange all cheques to be made payable to "Avant-garde Services Pte Ltd" and crossed "A/C Payee Only".<br/>
        Alternatively, for Bank Transfer / Electronic Payment please find our bank details as follows:<br/>
        UOB Bank (7375)<br/>
        Current A/C : 3733169263<br/>
        Bank Swift Code : UOVBSGSG<br/>
        Corporate PayNow : 201017519Z
        """
        story.append(Paragraph(footer_text, normal_style))
        story.append(Spacer(1, 20))
        
        # Footer with QR code and contact info
        # Create a table for the footer with QR code on left and contact info on right
        footer_data = []
        
        # Add QR code if available
        if qr_path and os.path.exists(qr_path):
            try:
                # 1.2cm = 34 points (1cm = 28.35 points)
                qr_image = Image(qr_path, width=34, height=34)
                footer_data.append([qr_image, ''])
            except:
                # If QR code fails to load, just add an empty cell
                footer_data.append(['', ''])
        
        # Add contact info and page number
        contact_text = "support@avant-garde.com.sg | +65 6666 1234"
        page_text = f"Page 1 of 1"  # ReportLab doesn't easily support dynamic page numbering
        # Use Paragraph to properly render HTML tags like <br/>
        footer_paragraph = Paragraph(f"{contact_text}<br/>{page_text}", normal_style)
        footer_data.append(['', footer_paragraph])
        
        footer_table = Table(footer_data, colWidths=[1.5*inch, 4.5*inch])
        footer_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(footer_table)

        # Build PDF
        doc.build(story)
        
        invoice.file_path = f"/billing_invoices/{filename}"
        invoice.total_amount = float(total_amount)
        db.session.commit()
        logging.info(f"Invoice PDF created at: {pdf_path}")
        InvoiceService.cleanup_old_pdfs(output_folder)
        
        # Return the PDF file for download
        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )

    @staticmethod
    def generate_invoice_pdf(invoice):
        """Wrapper method for backward compatibility - calls ReportLab implementation"""
        return InvoiceService.generate_invoice_pdf_reportlab(invoice)

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
    def build_particulars(job, service_name=None):
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

        # Add service name as first line if provided
        if service_name:
            lines.append(service_name)

        # Add route information
        if pickups[0]:
            lines.append(f"{pickups[0]} → {dropoffs[0] if dropoffs[0] else ''}")
        else:
            # Fallback to original format if no pickup location
            if pickups[0]:
                lines.append(f"ⓟ{pickups[0]}")
            for i, loc in enumerate(pickups[1:], start=1):
                if loc:
                    lines.append(f" > {loc} (Stop {i})")
            if dropoffs[0]:
                lines.append(f"Ⓓ {dropoffs[0]}")
            for loc in dropoffs[1:]:
                if loc:
                    lines.append(f" • {loc}")

        # Build 3rd line with extra pickup charges and extra services
        third_line_parts = []

        # Part 1: Extra Pickup/Dropoff charges (count pickups and dropoffs with price > 0)
        pickup_prices = [
            getattr(job, 'pickup_loc1_price', 0) or 0,
            getattr(job, 'pickup_loc2_price', 0) or 0,
            getattr(job, 'pickup_loc3_price', 0) or 0,
            getattr(job, 'pickup_loc4_price', 0) or 0,
            getattr(job, 'pickup_loc5_price', 0) or 0,
        ]

        dropoff_prices = [
            getattr(job, 'dropoff_loc1_price', 0) or 0,
            getattr(job, 'dropoff_loc2_price', 0) or 0,
            getattr(job, 'dropoff_loc3_price', 0) or 0,
            getattr(job, 'dropoff_loc4_price', 0) or 0,
            getattr(job, 'dropoff_loc5_price', 0) or 0,
        ]

        # Count non-zero pickup and dropoff prices and sum them
        extra_pickup_count = sum(1 for price in pickup_prices if price > 0)
        extra_dropoff_count = sum(1 for price in dropoff_prices if price > 0)
        extra_pickup_total = sum(pickup_prices)
        extra_dropoff_total = sum(dropoff_prices)

        total_count = extra_pickup_count + extra_dropoff_count
        total_amount = extra_pickup_total + extra_dropoff_total

        if total_count > 0:
            third_line_parts.append(f"Extra Pickup/Dropoff x {total_count} = ${total_amount:.2f}")

        # Part 2: Extra Services from extra_services field
        extra_services = getattr(job, 'extra_services_data', [])

        if extra_services:
            for service in extra_services:
                if isinstance(service, dict):
                    price = service.get('price', 0)
                    third_line_parts.append(f"Extra Service = ${float(price):.2f}")

        # Add the 3rd line if there are any extra charges
        if third_line_parts:
            lines.append(" | ".join(third_line_parts))

        return "\n".join(lines)


    def unpaid_invoice_download(invoice_id):
        
        if not isinstance(invoice_id, int) or invoice_id <= 0:
            raise ValueError(f"Invalid invoice_id: {invoice_id}")
        
        # Check if WeasyPrint is available and working
        if not WEASYPRINT_AVAILABLE:
            # Fallback to ReportLab implementation
            current_app.logger.warning("WeasyPrint not available, falling back to ReportLab for invoice generation")
            invoice = Invoice.query.get(invoice_id)
            if not invoice:
                raise ValueError(f"Invoice not found: {invoice_id}")
            return InvoiceService.generate_invoice_pdf_reportlab(invoice)
        
        # Test if WeasyPrint is actually working
        try:
            import weasyprint
        except Exception as weasyprint_error:
            current_app.logger.warning(f"WeasyPrint import failed: {weasyprint_error}, falling back to ReportLab")
            invoice = Invoice.query.get(invoice_id)
            if not invoice:
                raise ValueError(f"Invoice not found: {invoice_id}")
            return InvoiceService.generate_invoice_pdf_reportlab(invoice)
            
        try:
            invoice = Invoice.query.get(invoice_id)
            customer = Customer.query.get(invoice.customer_id)
            # Load jobs with vehicle_type relationship eagerly loaded
            jobs = Job.query.options(db.joinedload(Job.vehicle_type)).filter_by(invoice_id=invoice_id).all()

            # Validate jobs first - fail fast with clear errors
            invalid_jobs = []
            for job in jobs:
                missing = []
                if not job.pickup_date:
                    missing.append('pickup_date')
                if not job.pickup_time:
                    missing.append('pickup_time')
                if not job.service_type:
                    missing.append('service_type')
                if job.final_price is None:
                    missing.append('final_price')
                if missing:
                    invalid_jobs.append(f"Job #{job.id}: missing {', '.join(missing)}")

            if invalid_jobs:
                error_msg = f"Cannot generate invoice {invoice_id}: " + "; ".join(invalid_jobs)
                current_app.logger.error(error_msg)
                raise ValueError(error_msg)

            service_names = [job.service_type for job in jobs if job.service_type]
            services = Service.query.filter(Service.name.in_(service_names)).all()
            service_map = {s.name: s for s in services}

            # Billing Settings
            try:
                user_settings = UserSettings.query.first()
                prefs = user_settings.preferences or {} if user_settings else {}
            except Exception as e:
                logger.error(f"Failed to fetch UserSettings: {e}")
                prefs = {}
            billing_settings = prefs.get("billing_settings", {})
            company_logo = billing_settings.get("company_logo", "")
            logo_path = Logo.safe_logo_path(company_logo)

            # GST
            gst_percent = InvoiceService._get_gst_percent(billing_settings)
        
            # Build items for py-doc-generator
            items = []
            for job in jobs:
                price_without_gst = Decimal(str(job.final_price or 0)) 
                service = service_map.get(job.service_type)
                # Get vehicle type name from job's vehicle_type relationship
                vehicle_type_name = ""
                if hasattr(job, 'vehicle_type') and job.vehicle_type:
                    vehicle_type_name = job.vehicle_type.name
                elif hasattr(job, 'vehicle_type_id') and job.vehicle_type_id:
                    # If we have vehicle_type_id but not the relationship, we can fetch it
                    from backend.models.vehicle_type import VehicleType
                    vehicle_type = VehicleType.query.get(job.vehicle_type_id)
                    if vehicle_type:
                        vehicle_type_name = vehicle_type.name
                    
                # Get customer reference from booking_ref field
                customer_reference = getattr(job, 'booking_ref', '') or ''
                    
                service_name = service.name if service else job.service_type
                items.append(InvoiceItem(
                    Date=job.pickup_date,
                    Time=job.pickup_time,
                    Job=f"#{job.id}",
                    Particulars=InvoiceService.build_particulars(job, service_name),
                    ServiceType=service_name,
                    VehicleType=vehicle_type_name,
                    CustomerReference=customer_reference,
                    amount=Decimal(str(job.final_price or 0)),
                    cash_collect=Decimal(str(job.cash_to_collect or 0))
                ))
        
            user_settings = UserSettings.query.first()
            prefs = user_settings.preferences or {} if user_settings else {}

            billing_settings = prefs.get("billing_settings", {})
            general_settings = prefs.get("general_settings", {})

            company_logo = billing_settings.get("company_logo", "")
            logo_path = Logo.safe_logo_path(company_logo)

            # GST
            raw_gst = billing_settings.get("gst_percent", 0) or 0
            gst_percent = Decimal(str(raw_gst))  

            # Always recompute from jobs for accuracy
            computed_total = sum(Decimal(str(job.final_price or 0)) for job in jobs)
            sub_total = computed_total

            # Log discrepancies for audit
            if invoice.total_amount is not None:
                stored = Decimal(str(invoice.total_amount))
                if abs(stored - computed_total) > Decimal("0.01"):
                    current_app.logger.warning(
                        f"Invoice {invoice.id} total mismatch: stored={stored}, "
                        f"computed={computed_total}. Using computed."
                    )
                
            gst_amount = (sub_total * gst_percent / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            grand_total = (sub_total + gst_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            cash_collect_total = sum(item.cash_collect for item in items)

            # Footer Data
            general_settings = prefs.get("general_settings", {})
            company_address = general_settings.get("company_address", "")
            email = general_settings.get("email_id", "")
            contact_number = general_settings.get("contact_number", "")

            # Payment Info and QR Code
            payment_info = billing_settings.get("billing_payment_info", "")
            qr_path = Logo.safe_logo_path(billing_settings.get("billing_qr_code_image", ""))

            # Build the py-doc-generator Invoice object

            # Build customer contact info
            customer_contact = ""
            if customer.mobile:
                customer_contact = customer.mobile
            elif customer.email:
                customer_contact = customer.email

            # Format customer address with intelligent line breaks
            customer_address = customer.address or ""

            # If address doesn't have newlines, add line breaks intelligently
            if customer_address and '\n' not in customer_address:
                # Split long addresses at commas for better readability
                # But only if address is longer than 40 characters
                if len(customer_address) > 40 and ',' in customer_address:
                    parts = [part.strip() for part in customer_address.split(',')]
                    # Group parts to avoid too many short lines
                    if len(parts) >= 2:
                        # First line: first part, Second line: rest
                        customer_address = parts[0] + '\n' + ', '.join(parts[1:])

            # Add country and zip code if available
            if customer.country or customer.zip_code:
                country_zip_line = ""
                if customer.country:
                    country_zip_line = customer.country
                if customer.zip_code:
                    country_zip_line += f" - {customer.zip_code}" if country_zip_line else customer.zip_code
                if customer_address:
                    customer_address += f"\n{country_zip_line}"
                else:
                    customer_address = country_zip_line

            doc_invoice = DocInvoice(
            number=f"INV-{invoice.id}",
            date=(invoice.date.date() if hasattr(invoice.date, "date") else invoice.date),
            from_company=customer.name,
            from_email=customer.email or "-",
            from_mobile=customer.mobile or "-",
            to_company=customer.name,
            to_address=customer_address,
            customer_contact=customer_contact,
            items=items,
            notes="Thank you for your business!",
            currency="SGD",
            logo_path=logo_path,
            sub_total=sub_total,
            gst_amount=gst_amount,
            cash_collect_total=cash_collect_total,
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
                repos_root = Path(current_app.root_path).resolve().parents[1]
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
                    # Try fallback to ReportLab
                    current_app.logger.warning("WeasyPrint failed, falling back to ReportLab for invoice generation")
                    return InvoiceService.generate_invoice_pdf_reportlab(invoice)

                # Step 3: Atomically move the file into place
                os.replace(temp_pdf, pdf_final_path)
                temp_pdf = None  # Prevent cleanup in finally block
                current_app.logger.info(f"Invoice PDF saved atomically: {pdf_final_path}")

            except Exception as e:
                current_app.logger.error(
                    f"Error during PDF generation or atomic save for invoice {invoice_id}: {e}",
                    exc_info=True
                )
                # Try fallback to ReportLab
                current_app.logger.warning(f"WeasyPrint failed: {e}, falling back to ReportLab for invoice generation")
                return InvoiceService.generate_invoice_pdf_reportlab(invoice)
            finally:
                if temp_pdf and temp_pdf.exists():
                    try:
                        temp_pdf.unlink()
                        current_app.logger.debug(f"Cleaned up temp file: {temp_pdf}")
                    except Exception as cleanup_err:
                        current_app.logger.warning(f"Failed to delete temp file {temp_pdf}: {cleanup_err}")  
  

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
