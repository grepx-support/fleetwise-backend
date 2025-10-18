from backend.models import invoice
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from backend.services.invoice_service import InvoiceService, ServiceError,PaymentService
from backend.schemas.invoice_schema import InvoiceSchema
from datetime import datetime
from decimal import Decimal
from backend.models.invoice import Invoice, Payment

import logging
from flask_security import roles_required, roles_accepted, auth_required, current_user
from backend.extensions import db

invoice_bp = Blueprint('invoice', __name__)
schema = InvoiceSchema(session=db.session)
schema_many = InvoiceSchema(many=True, session=db.session)
import os
from backend.models.invoice import Invoice
from backend.models.invoice import Payment
 
from werkzeug.utils import secure_filename
@invoice_bp.route('/invoices', methods=['GET'])
@roles_accepted('admin', 'manager')
def list_invoices():
    try:
        invoices = InvoiceService.get_all()
        return jsonify(schema_many.dump(invoices)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in list_invoices: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@invoice_bp.route('/invoices/<int:invoice_id>', methods=['GET'])
@auth_required()
def get_invoice(invoice_id):
    try:
        invoice = InvoiceService.get_by_id(invoice_id)
        if not invoice:
            return jsonify({'error': 'Invoice not found'}), 404
        # Only allow access if admin/manager or the customer who owns the invoice
        if current_user.has_role('admin') or current_user.has_role('manager') or invoice.customer_id == current_user.id:
            return jsonify(schema.dump(invoice)), 200
        return jsonify({'error': 'Forbidden'}), 403
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in get_invoice: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@invoice_bp.route('/invoices', methods=['POST'])
@roles_accepted('admin', 'manager')
def create_invoice():
    try:
        data = request.get_json()
        errors = schema.validate(data)
        if errors:
            return jsonify(errors), 400
        invoice = InvoiceService.create(data)
        return jsonify(schema.dump(invoice)), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in create_invoice: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@invoice_bp.route('/invoices/<int:invoice_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_invoice(invoice_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        invoice = InvoiceService.update(invoice_id, data)
        if not invoice:
            return jsonify({'error': 'Invoice not found'}), 404
        return jsonify(schema.dump(invoice)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_invoice: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@invoice_bp.route('/invoices/<int:invoice_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def delete_invoice(invoice_id):
    try:
        success = InvoiceService.delete(invoice_id)
        if not success:
            return jsonify({'error': 'Invoice not found'}), 404
        return jsonify({'message': 'Invoice deleted'}), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in delete_invoice: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@invoice_bp.route('/invoices/generate', methods=['POST'])
@roles_accepted('admin', 'manager')
def generate_invoice():
    try:
        data = request.get_json()
        job_ids = data.get('job_ids')
        customer_id = data.get('customer_id')
        if not job_ids or not customer_id:
            return jsonify({'error': 'job_ids and customer_id are required'}), 400
        result = InvoiceService.generate_invoice_for_jobs(job_ids, customer_id)
        if isinstance(result, dict) and result.get('error'):
            return jsonify(result), 400
        invoice = result.get('invoice')
        response = {
            'invoice': schema.dump(invoice),
            'total_amount': result.get('total_amount'),
            'breakdown': result.get('breakdown')
        }
        return jsonify(response), 201
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in generate_invoice: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@invoice_bp.route('/invoices/report', methods=['GET'])
def billing_report():
    try:
        customer_id = request.args.get('customer_id', type=int)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        status = request.args.get('status')
        report = InvoiceService.get_billing_report(
            customer_id=customer_id,
            start_date=start_date,
            end_date=end_date,
            status=status
        )
        return jsonify(report), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in billing_report: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500 
    
@invoice_bp.route('/invoices/unpaid', methods=['GET'])
@roles_accepted('admin', 'manager')
def invoices_with_jobs_by_status():
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('pageSize', 10))
        status = request.args.get('status')
        customer_name = request.args.get('customer')
        service_type = request.args.get('serviceType')
        result = InvoiceService.invoices_with_jobs_by_status(page=page,
                                                 page_size=page_size,status=status,customer_name=customer_name,
                                                 service_type=service_type)
        invoices = result.get('invoices')
        return jsonify({
            'items': schema_many.dump(invoices),
            'total': result.get('total'),
            'page': page,
            'pageSize': page_size
        }), 200

    except Exception as e:
        import logging
        logging.error(f"Unhandled error in invoices_with_jobs_by_status: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500
    
@invoice_bp.route('/invoices/remove/<int:id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def remove_invoice(id):
    try:
        invoice = InvoiceService.remove_invoice(id)
        return jsonify(invoice), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in remove_invoice: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500 
    
@invoice_bp.route('/invoices/statusUpdate/<int:invoice_id>', methods=['PUT'])
@roles_accepted('admin', 'manager')
def update_invoice_status(invoice_id):
    try:
        data = request.get_json()
        errors = schema.validate(data, partial=True)
        if errors:
            return jsonify(errors), 400
        invoice = InvoiceService.update_status(invoice_id, data)
        if not invoice:
            return jsonify({'error': 'Invoice not found'}), 404
        return jsonify(schema.dump(invoice)), 200
    except ServiceError as se:
        return jsonify({'error': se.message}), 400
    except Exception as e:
        logging.error(f"Unhandled error in update_invoice: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

# @invoice_bp.route('/invoices/download/<int:invoice_id>', methods=['GET'])
# @roles_accepted('admin', 'manager')
# def download_invoice(invoice_id):
#     try:
#         invoice = Invoice.query.get(invoice_id)
#         if not invoice:
#             return jsonify({'error': 'Invoice not found'}), 404

#         if not invoice.file_path:
#             return jsonify({'error': 'Invoice PDF not generated yet'}), 404

#         original_filename = os.path.basename(invoice.file_path)
#         filename = secure_filename(original_filename)
#         if not filename or '..' in filename:
#             return jsonify({'error': 'Invalid filename'}), 400

#         invoices_dir = os.path.join(current_app.root_path, 'billing_invoices')
#         safe_path = os.path.abspath(os.path.join(invoices_dir, filename))

#         if not os.path.commonpath([safe_path, invoices_dir]) == invoices_dir:
#             return jsonify({'error': 'Invalid path'}), 400
#         if not os.path.isfile(safe_path):
#             return jsonify({'error': 'Invoice file not found on server'}), 404

#         return send_from_directory(directory=invoices_dir, path=filename, as_attachment=True)
#     except Exception as e:
#         logging.error(f"Unhandled error in download_invoice: {e}", exc_info=True)
#         return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
    
# generate_payment_receipt

@invoice_bp.route('/invoices/download/<int:invoice_id>', methods=['GET'])
@roles_accepted('admin', 'manager')
def download_invoice(invoice_id):
    try:
        response = PaymentService.generate_payment_receipt(invoice_id)
        if not response:
            return jsonify({'error': 'Invoice not found'}), 404
        return response
    except Exception as e:
        logging.error(f"Unhandled error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to generate invoice PDF'}), 500

@invoice_bp.route('/invoices/unpaid/download/<int:invoice_id>', methods=['GET'])
@roles_accepted('admin', 'manager')
def download_unpaid_invoice(invoice_id):
    try:
        response = InvoiceService.unpaid_invoice_download(invoice_id)
        if not response:
            return jsonify({'error': 'Invoice not found'}), 404
        return response
    except Exception as e:
        logging.error(f"Unhandled error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to generate invoice PDF'}), 500
    



    
@invoice_bp.route('/invoices/<int:invoice_id>/payments', methods=['GET'])
@auth_required()
def get_invoice_payments(invoice_id):
    try:
        invoice = Invoice.query.get_or_404(invoice_id)

        # Check permission
        if not (current_user.has_role('admin') or 
                current_user.has_role('manager') or 
                invoice.customer_id == current_user.id):
            return jsonify({"error": "Forbidden"}), 403

        payments = [
            {
                "id": p.id,
                "amount": p.amount,
                "date": p.date.isoformat(),
                "reference_number": p.reference_number,
                "notes": p.notes
            }
            for p in invoice.payments
        ]

        return jsonify({
            "invoice_id": invoice.id,
            "total_amount": invoice.total_amount,
            "paid_amount": invoice.paid_amount,
            "remaining_amount": invoice.remaining_amount,
            "status": invoice.status,
            "payments": payments
        }), 200

    except Exception as e:
        logging.error(f"Unhandled error in get_invoice_payments: {e}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred"}), 500


   
@invoice_bp.route('/invoices/<int:invoice_id>/payments', methods=['POST'])
@auth_required()
def add_payment(invoice_id):
    try:
        data = request.get_json()
        amount = data.get("amount")
        reference_number = data.get("reference_number")
        notes = data.get("notes")

        # Use Decimal for validation
        if not amount or Decimal(str(amount)) <= 0:
            return jsonify({"error": "Invalid payment amount"}), 400

        # Lock the invoice row to avoid race conditions
        #invoice = Invoice.query.with_for_update().get_or_404(invoice_id)
        # Lock the invoice row to avoid race conditions
        invoice = Invoice.query.with_for_update().filter_by(id=invoice_id).first_or_404()


        # Calculate current paid and remaining dynamically
        current_paid = sum(Decimal(str(p.amount)) for p in invoice.payments)
        total_amount = Decimal(str(invoice.total_amount))
        remaining = total_amount - current_paid

        if remaining <= 0:
            return jsonify({"error": "Invoice already fully paid"}), 400

        if Decimal(str(amount)) > remaining:
            return jsonify({"error": f"Payment exceeds remaining balance ({remaining})"}), 400

        # Create payment (not committed yet)
        payment = Payment(
            invoice_id=invoice.id,
            amount=Decimal(str(amount)),
            reference_number=reference_number,
            notes=notes,
            date=datetime.utcnow(),
        )
        db.session.add(payment)

        # Keep all state updates inside the try block so rollback is clean
        try:
            # Ensure payment.id is available for receipt naming
            db.session.flush()

            # Generate receipt
            PaymentService.generate_payment_receipt(payment.invoice_id)

            # Update invoice state **once only**
            current_paid += Decimal(str(amount))
            remaining = total_amount - current_paid

            # Persist new remaining balance + status
            invoice.remaining_amount_invoice = remaining
            invoice.status = "Paid" if remaining == 0 else "Partially Paid"

            db.session.commit()

        except Exception as receipt_error:
            db.session.rollback()
            logging.error(f"Receipt generation failed: {receipt_error}", exc_info=True)
            return jsonify({"error": f"Payment processing failed: {str(receipt_error)}"}), 500

        # Response comes from DB-backed values (not double-counted)
        return jsonify({
            "message": "Payment added successfully",
            "payment_id": payment.id,
            "remaining_amount": str(invoice.remaining_amount_invoice),
            "status": invoice.status,
            "receipt_path": payment.receipt_path
        }), 201

    except Exception as e:
        db.session.rollback()
        logging.error(f"Unhandled error in add_payment: {e}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred"}), 500

# @invoice_bp.route('/invoices/<int:invoice_id>/payments/<int:payment_id>', methods=['DELETE'])
# @auth_required()
# def delete_invoice_payment(invoice_id, payment_id):
#     try:
#         invoice = Invoice.query.get_or_404(invoice_id)

#         # Permission check
#         if not (current_user.has_role('admin') or 
#                 current_user.has_role('manager') or 
#                 invoice.customer_id == current_user.id):
#             return jsonify({"error": "Forbidden"}), 403

#         payment = next((p for p in invoice.payments if p.id == payment_id), None)
#         if not payment:
#             return jsonify({"error": "Payment not found"}), 404

#         db.session.delete(payment)
#         db.session.commit()

#         return jsonify({"message": "Payment deleted successfully"}), 200

#     except Exception as e:
#         logging.error(f"Error deleting payment: {e}", exc_info=True)
#         db.session.rollback()
#         return jsonify({"error": "An unexpected error occurred"}), 500
# @invoice_bp.route('/invoices/<int:invoice_id>/payments/<int:payment_id>', methods=['DELETE'])
# @auth_required()
# def delete_invoice_payment(invoice_id, payment_id):
#     try:
#         invoice = Invoice.query.get_or_404(invoice_id)

#         # Permission check
#         if not (current_user.has_role('admin') or 
#                 current_user.has_role('manager') or 
#                 invoice.customer_id == current_user.id):
#             return jsonify({"error": "Forbidden"}), 403

#         payment = next((p for p in invoice.payments if p.id == payment_id), None)
#         if not payment:
#             return jsonify({"error": "Payment not found"}), 404

        # Delete the payment
#         # payment = Payment.query.get(payment_id)
#         db.session.delete(payment)
#         db.session.flush()
        

# # Recalculate
#         invoice.recalc_amounts()   # works after removing @property
#         db.session.commit()

#         return jsonify({
#          "message": "Payment deleted successfully",
#          "invoice_id": invoice.id,
#         "total_amount": str(invoice.total_amount),
#         "remaining_amount_invoice": str(invoice.remaining_amount_invoice),
#          "status": invoice.status
#         }), 200


#     except Exception as e:
#         logging.error(f"Error deleting payment: {e}", exc_info=True)
#         db.session.rollback()
#         return jsonify({"error": "An unexpected error occurred"}), 500

@invoice_bp.route('/invoices/<int:invoice_id>/payments/<int:payment_id>', methods=['DELETE'])
@roles_accepted('admin', 'manager')
def delete_payment(invoice_id, payment_id):
    try:
        # invoice = Invoice.query.get_or_404(invoice_id)
        invoice = (
            db.session.query(Invoice)
            .filter(Invoice.id == invoice_id)
            .with_for_update()
            .first_or_404()
        )
        # Find the payment
        payment = (
            db.session.query(Payment)
            .filter_by(id=payment_id, invoice_id=invoice_id)
            .with_for_update()
            .first()
        )
        if not payment:
            return jsonify({'error': 'Payment not found'}), 404
        #payment = Payment.query.filter_by(id=payment_id, invoice_id=invoice_id).first()
        if not current_user.has_role('admin') and invoice.customer_id != current_user.id and not payment:
            return jsonify({'error': 'Forbidden'}), 403

        # Find the associated invoice
        # invoice = Invoice.query.get_or_404(invoice_id)

        # Delete the payment
        db.session.delete(payment)

        # Update invoice's remaining_amount_invoice and status
        invoice.update_remaining_amount()
        invoice.update_status()

        # Commit changes to the database
        db.session.commit()

        # Serialize the updated invoice
        invoice_schema = InvoiceSchema()
        return jsonify(invoice_schema.dump(invoice)), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error deleting payment {payment_id} for invoice {invoice_id}: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500