from backend.services.driver_service import DriverService
from backend.services.photo_backup_service import PhotoBackupService
from flask import Blueprint, request, jsonify, url_for, current_app, send_from_directory
from flask_security.decorators import roles_accepted, auth_required
from flask_security.utils import current_user
from sqlalchemy.exc import OperationalError
from datetime import date, datetime, timezone
from sqlalchemy import cast, Date, case
import logging, time
import hashlib
from backend.extensions import db
from backend.models.job import Job, JobStatus
from backend.models.settings import UserSettings
from backend.models.job_photo import JobPhoto
from backend.models.photo_config import PhotoConfig
from backend.models.driver_remark import DriverRemark
from backend.models.job_audit import JobAudit
from backend.models.job_monitoring_alert import JobMonitoringAlert
from backend.models.user import User
from backend.services.push_notification_service import PushNotificationService
import pytz
from dateutil.parser import parse
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
from werkzeug.utils import secure_filename
from PIL import Image
from io import BytesIO
from sqlalchemy.orm import joinedload

# ---- Blueprint for mobile driver-related APIs ----
mobile_driver_bp = Blueprint('mobile_driver', __name__)

# Initialize limiter for rate limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Configurable business rule constants
MAX_CASH_TO_COLLECT = lambda: current_app.config.get('MAX_CASH_TO_COLLECT', 100000)

def validate_cash_collection(cash_to_collect, new_status):
    """Validate cash collection amount and status requirements.
    
    Args:
        cash_to_collect: The cash amount to validate (float or None)
        new_status: The target job status
        
    Returns:
        tuple: (error_response, None) if validation fails, (None, float_value) if validation passes
    """
    if cash_to_collect is None:
        return None, None
        
    if new_status != JobStatus.JC.value:
        return jsonify({
            'error': 'cash_to_collect can only be updated when status is JC (Job Completed)'
        }), 400
        
    try:
        float_value = float(cash_to_collect)
        if float_value < 0:
            return jsonify({'error': 'cash_to_collect cannot be negative'}), 400
        max_allowed = MAX_CASH_TO_COLLECT()
        if float_value > max_allowed:
            return jsonify({
                'error': f'cash_to_collect exceeds maximum allowed value of {max_allowed}'
            }), 400
        return None, float_value
    except (TypeError, ValueError):
        return jsonify({'error': 'cash_to_collect must be a valid number'}), 400

limiter = Limiter(key_func=get_remote_address)

def init_app(app):
    """Initialize the limiter with the Flask app"""
    limiter.init_app(app)

# Retry configs for DB locking issues (SQLite can lock under concurrency)
MAX_RETRIES = 5
RETRY_DELAY = 2

# Allowed photo formats
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}

# UTC timestamp reference
timestamp = datetime.now(timezone.utc)


# ---------------- DRIVER DASHBOARD ----------------
@mobile_driver_bp.route('/driver/dashboard/<int:driver_id>', methods=['GET'])
@auth_required()
def driver_dashboard(driver_id):
    """
    Driver Dashboard API
    - Returns driver info, vehicle, shift (if applicable)
    - Counts today's jobs
    - Counts completed jobs
    """
    try:
        # ---- Role-based access check ----
        if not (
            current_user.has_role('admin') or
            current_user.has_role('manager') or
            current_user.driver_id == driver_id
        ):
            return jsonify({'error': 'Forbidden'}), 403
        
        # Fetch driver info from service layer
        driver = DriverService.get_by_id(driver_id)
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        
        # Basic driver details
        name = driver.name
        vehicle_number = driver.vehicle.number if driver.vehicle_id and driver.vehicle else None
        shift = getattr(driver, "shift", "Not Assigned")  # optional field

        # ---- Count today's jobs ----
        # Use consistent date calculation as in the jobs endpoint
        today_date = date.today().strftime("%Y-%m-%d")
        # Count all jobs for today that are not completed (not in JC status)
        todays_job_count = (
            Job.query.filter(
                Job.driver_id == driver_id,
                Job.pickup_date == today_date,
                Job.status != "jc"
            ).count()
        )

        # Debug print (can be removed in production)
        todays_jobs = (
            Job.query.filter(
                Job.driver_id == driver_id,
                Job.pickup_date == today_date,
                Job.status != "jc"
            ).all()
        )
        print("today_job_count", todays_job_count, todays_jobs, driver_id)

        # ---- Count completed jobs (status = JC or SD) ----
        completed_job_count = (
            Job.query.filter(
                Job.driver_id == driver_id,
                Job.status.in_(["jc", "sd"])
            ).count()
        )

        # Build response
        response = {
            "name": name,
            "vehicleNumber": vehicle_number,
            "shift": shift,
            "todaysJobCount": todays_job_count,
            "completedJobCount": completed_job_count
        }

        return jsonify(response), 200

    except Exception as e:
        logging.error(f"Unhandled error in driver_dashboard: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500
    


# ---------------- UPDATE JOB STATUS ----------------
@mobile_driver_bp.route('/driver/update_status', methods=['POST'])
@auth_required()
@roles_accepted('admin', 'manager', 'driver')
def update_driver_job_status():
    """
    Update Job Status API
    - Allows driver/admin/manager to update job status
    - Enforces valid status transitions
    - Adds optional driver remark for each stage
    - Allows updating cash_to_collect value (tracks changes in audit)
    - Returns all remarks in response
    - Retries in case of DB lock issues
    """
    data = request.get_json()

    driver_id = data.get('driver_id')
    job_id = data.get('job_id')
    new_status = data.get('status')
    remark_text = data.get('remark')   # NEW: optional remark
    cash_to_collect = data.get('cash_to_collect')  # NEW: optional cash to collect for JC status



    # ---- Validation ----
    if not driver_id or not job_id or not new_status:
        return jsonify({'error': 'Missing driver_id, job_id, or status'}), 400
    

    try:
        driver_id = int(driver_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid driver_id format'}), 400

    # ---- Role-based access check ----
    if not (
        current_user.has_role('admin') or
        current_user.has_role('manager') or
        current_user.driver_id == driver_id
    ):
        return jsonify({'error': 'Forbidden'}), 403

    # Allowed statuses for update
    ALLOWED_STATUS = [
        JobStatus.CONFIRMED.value,
        JobStatus.OTW.value,   # On the Way
        JobStatus.OTS.value,   # On the Spot
        JobStatus.POB.value,   # Person On Board
        JobStatus.JC.value,    # Job Completed
        JobStatus.SD.value     # Stand Down

    ]
    if new_status not in ALLOWED_STATUS:
        return jsonify({'error': 'Invalid status'}), 400

    # Validate cash_to_collect using the centralized validation function
    error_response, validated_cash = validate_cash_collection(cash_to_collect, new_status)
    if error_response:
        return error_response
    cash_to_collect = validated_cash  # Now safely converted to float or None

    # ---- Retry loop for DB lock handling ----
    for attempt in range(MAX_RETRIES):
        try:
            job = (
                Job.query
                .with_for_update()
                .filter_by(id=job_id, driver_id=driver_id)
                .first()
            )

            if not job:
                return jsonify({'error': 'Job not found'}), 404

            logging.info(f"[Attempt {attempt+1}] Job {job_id}: Current={job.status}, "
                         f"Requested={new_status}, Driver={driver_id}")

            # Validate transition
            if not job.can_transition_to(new_status):
                return jsonify({'error': 'Invalid status transition'}), 400

            # Case 1: Status already set → only allow remarks, prevent cash updates
            if job.status == new_status:
                # Prevent cash updates when status isn't changing
                if cash_to_collect is not None:
                    return jsonify({
                        'error': 'cash_to_collect can only be set during initial transition to JC status'
                    }), 400

                # Only process remark if provided
                if remark_text:
                    audit_record = JobAudit(
                        job_id=job.id,
                        changed_by=current_user.id,
                        old_status=job.status,
                        new_status=new_status,
                        reason='Status update with remark'
                    )
                    db.session.add(audit_record)

                    remark = DriverRemark(
                        driver_id=driver_id,
                        job_id=job.id,
                        remark=remark_text
                    )
                    db.session.add(remark)

                db.session.commit()

                remarks = [
                    {"id": r.id, "remark": r.remark, "created_at": r.created_at.isoformat()}
                    for r in DriverRemark.query.filter_by(job_id=job.id).all()
                ]

                return jsonify({
                    'message': 'Remark added' if remark_text else 'Status already set',
                    'job_id': job.id,
                    'status': job.status,
                    'cash_to_collect': float(job.cash_to_collect) if job.cash_to_collect is not None else None,
                    'remarks': remarks
                }), 200

            # Case 2: Status change → update and add remark if provided
            old_status = job.status  # Store old status for audit
            job.status = new_status
            job.updated_at = datetime.now(timezone.utc)

            # --- Track start & end time ---
            if new_status == JobStatus.OTW.value:
                if job.start_time is None:
                    job.start_time = datetime.now(timezone.utc)
                # Clear monitoring alerts when job status is updated to OTW
                from backend.models.job_monitoring_alert import JobMonitoringAlert
                JobMonitoringAlert.clear_alert(job_id)
            if new_status in [JobStatus.JC.value, JobStatus.SD.value]:
                if job.end_time is None:
                    job.end_time = datetime.now(timezone.utc)

            # Handle cash_to_collect update
            cash_updated = False
            old_cash = float(job.cash_to_collect) if job.cash_to_collect is not None else None
            if cash_to_collect is not None and old_cash != cash_to_collect:
                job.cash_to_collect = cash_to_collect
                cash_updated = True

            # Create audit record for status change
            if cash_updated:
                audit_reason = f'Status updated via Driver API (Cash to collect updated from {old_cash} to {cash_to_collect})'
            else:
                audit_reason = 'Status updated via Driver API'

            # Prepare additional_data for audit
            additional_data = {}
            if cash_updated:
                additional_data['cash_to_collect'] = {
                    'old_value': float(old_cash) if old_cash is not None else None,
                    'new_value': float(cash_to_collect)
                }

            audit_record = JobAudit(
                job_id=job.id,
                changed_by=current_user.id,  # Always valid due to @auth_required()
                old_status=old_status,
                new_status=new_status,
                reason=audit_reason,
                additional_data=additional_data if additional_data else None
            )
            db.session.add(audit_record)

            if remark_text:
                remark = DriverRemark(
                    driver_id=driver_id,
                    job_id=job.id,
                    remark=remark_text
                )
                db.session.add(remark)

            db.session.commit()

            remarks = [
                {"id": r.id, "remark": r.remark, "created_at": r.created_at.isoformat()}
                for r in DriverRemark.query.filter_by(job_id=job.id).all()
            ]

            return jsonify({
                'message': 'Status updated',
                'job_id': job.id,
                'new_status': new_status,
                'cash_to_collect': float(job.cash_to_collect) if job.cash_to_collect is not None else None,
                'remarks': remarks
            }), 200
        
        except OperationalError as e:
            db.session.rollback()
            if 'database is locked' in str(e).lower():
                logging.warning(f"[Attempt {attempt+1}] Database locked "
                                f"for job {job_id}, driver {driver_id}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))  # exponential backoff
                    continue
                logging.error(f"Database remained locked after {MAX_RETRIES} attempts")
                return jsonify({'error': 'Database busy. Try again later.'}), 503
            logging.error(f"Database error: {e}", exc_info=True)
            return jsonify({'error': 'Database error'}), 500

        except Exception as e:
            db.session.rollback()
            logging.error(f"Unexpected error: {e}", exc_info=True)
            return jsonify({'error': 'Update failed'}), 500

    return jsonify({'error': 'Database busy. Try again later.'}), 503


# ---------------- UPLOAD JOB PHOTO ----------------
@mobile_driver_bp.route('/driver/upload_photo', methods=['POST'])
@auth_required()
@roles_accepted('admin', 'manager', 'driver')
def upload_job_photo():
    """
    Upload Job Photo API
    - Uploads and compresses job photos
    - Validates stage, format, size, and duplicates
    - Saves file with unique name
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in request'}), 400

    file = request.files['file']
    job_id = request.form.get('job_id')
    driver_id = request.form.get('driver_id')
    stage = request.form.get('stage')

    # ---- Validation ----
    if not file or file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not job_id or not driver_id or not stage:
        return jsonify({'error': 'Missing job_id, driver_id, or stage'}), 400

    try:
        job_id = int(job_id)
        driver_id = int(driver_id)
    except ValueError:
        return jsonify({'error': 'Invalid job_id or driver_id format'}), 400

    # Access check
    if not (
        current_user.has_role('admin') or
        current_user.has_role('manager') or
        current_user.driver_id == driver_id
    ):
        return jsonify({'error': 'Forbidden'}), 403

    # Validate job exists
    job = Job.query.filter_by(id=job_id, driver_id=driver_id).first()
    if not job:
        return jsonify({'error': 'Job not found'}), 404


    # Fetch photo config from UserSettings.preferences['photo_config']
    # Directly collect photo_config from first UserSettings row
    user_settings = UserSettings.query.filter_by(user_id=current_user.id).first()
    config = None
    if user_settings and user_settings.preferences:
        photo_configs = user_settings.preferences.get('photo_config', [])
        if not isinstance(photo_configs, list):
            photo_configs = [photo_configs] if photo_configs else []
        config = next((c for c in photo_configs if c.get('stage') == stage), None)
    if not config:
        config = {'stage': stage, 'max_photos': 3, 'max_size_mb': 2.0, 'allowed_formats': 'jpg,png'}

    # Max photos per stage
    existing_count = JobPhoto.query.filter_by(job_id=job_id, stage=stage).count()
    if existing_count >= int(config.get('max_photos', 1)):
        return jsonify({'error': f"Max {config.get('max_photos', 1)} photos allowed for stage {stage}"}), 400

    # Allowed formats
    # Consolidate validation to ensure filename exists and has extension
    if not file.filename or '.' not in file.filename:
        return jsonify({'error': 'Invalid file name'}), 400
    ext = file.filename.rsplit('.', 1)[1].lower()
    allowed_formats = config.get('allowed_formats', 'jpg,png')
    allowed_formats_list = [fmt.strip() for fmt in allowed_formats.split(',')]
    if ext not in allowed_formats_list:
        return jsonify({'error': f'Format not allowed. Allowed: {allowed_formats}'}), 400

    # ---- Process image (compress & check size) ----
    try:
        # Check file size before reading into memory to prevent memory exhaustion
        if file.content_length and file.content_length > 10 * 1024 * 1024:  # 10MB limit
            return jsonify({'error': 'File too large'}), 400
            
        # Read file content first
        file_content = file.read()
        img = Image.open(BytesIO(file_content))
        img_io = BytesIO()
        img.save(img_io, format='JPEG', optimize=True, quality=85)
        img_io.seek(0)

        size_mb = len(img_io.getbuffer()) / (1024 * 1024)
        if size_mb > float(config.get('max_size_mb', 2.0)):
            return jsonify({'error': f"File exceeds max size of {config.get('max_size_mb', 2.0)} MB after compression"}), 400
    except Exception as e:
        return jsonify({'error': f'Image processing failed: {str(e)}'}), 500

    # ---- Check duplicate using hash ----
    file_hash = hashlib.md5(img_io.getbuffer()).hexdigest()
    duplicate = JobPhoto.query.filter_by(job_id=job_id, driver_id=driver_id, stage=stage, file_hash=file_hash).first()
    if duplicate:
        return jsonify({'error': 'Duplicate photo detected'}), 400

    # ---- Save file ----
    filename = secure_filename(f"{job_id}_{driver_id}_{stage}_{int(datetime.now(timezone.utc).timestamp())}.jpg")
    # Use the upload folder from Flask app config, with fallback if not set
    upload_folder = current_app.config.get('JOB_PHOTO_UPLOAD_FOLDER')
    if not upload_folder:
        backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        upload_folder = os.path.join(backend_root, 'static', 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    file_path = os.path.join(upload_folder, filename)

    # Prevent overwrite
    if os.path.exists(file_path):
        return jsonify({'error': 'File with same name already exists'}), 400

    temp_file_path = None
    job_photo = None

    try:
        # Step 1: Save to temporary folder
        with open(file_path, 'wb') as f:
            f.write(img_io.getbuffer())

        temp_file_path = file_path  # Track for cleanup
        logging.info(f"Photo saved to temporary location: {file_path}")

        # Step 2: Backup photo to fleetwise-storage
        photo_storage_root = current_app.config.get('PHOTO_STORAGE_ROOT')
        if not photo_storage_root:
            raise Exception("PHOTO_STORAGE_ROOT configuration not set")

        backup_service = PhotoBackupService(photo_storage_root)
        success, backup_path, error_msg = backup_service.backup_photo(file_path, filename)

        if not success:
            logging.error(f"Photo backup failed: {error_msg}")
            return jsonify({'error': f'Photo backup failed: {error_msg}'}), 500

        logging.info(f"Photo backed up successfully: {backup_path}")

        # Step 3: Database transaction - create and commit in single atomic transaction
        # This ensures database consistency: either photo record exists with valid file_path,
        # or no record exists at all (no partial/inconsistent state)
        try:
            job_photo = JobPhoto(
                job_id=job_id,
                driver_id=driver_id,
                stage=stage,
                file_path=backup_path,  # Store relative path from fleetwise-storage
                file_size=os.path.getsize(file_path) // 1024,
                file_hash=file_hash,    # store hash in DB
                filename=filename       # store filename for indexed lookups
            )
            db.session.add(job_photo)
            db.session.commit()
            logging.info(f"Photo record created in database: photo_id={job_photo.id}")

        except Exception as db_error:
            # Rollback database changes if commit failed
            db.session.rollback()
            logging.error(f"Database error: {str(db_error)}")
            raise Exception(f"Failed to save photo record: {str(db_error)}")

        # Step 4: Cleanup temporary file after successful database commit
        # Only cleanup after we're certain database transaction succeeded
        try:
            backup_service.cleanup_temporary_file(temp_file_path)
            logging.info(f"Cleaned up temporary file: {temp_file_path}")
        except Exception as cleanup_error:
            logging.warning(f"Failed to cleanup temp file {temp_file_path}: {cleanup_error}")
            # Don't fail the upload if cleanup fails - photo is already safe in fleetwise-storage

        logging.info(f"Photo upload completed: job_id={job_id}, backup_path={backup_path}")

        # Return file URL using the relative path
        file_url = url_for('uploaded_file', filename=filename, _external=True)
        return jsonify({
            'message': 'Photo uploaded successfully',
            'photo_id': job_photo.id,
            'file_path': backup_path,  # Return the backup path
            'file_url': file_url
        }), 201

    except Exception as e:
        # Comprehensive error handling with proper cleanup
        logging.error(f"Upload failed: {str(e)}")

        # Rollback any pending database transaction
        db.session.rollback()

        # Cleanup temporary file on any failure
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logging.info(f"Cleaned up temp file on error: {temp_file_path}")
            except Exception as cleanup_error:
                logging.warning(f"Failed to cleanup temp file {temp_file_path} on error: {cleanup_error}")

        return jsonify({'error': f'Upload failed: {str(e)}'}), 500


# ---------------- GET JOB PHOTOS ----------------
@mobile_driver_bp.route('/driver/job_photos', methods=['GET'])
@auth_required()
@roles_accepted('admin', 'manager', 'driver')
def get_job_photos():
    """
    Get Job Photos API
    - Returns all photos uploaded for a specific job
    """
    job_id = request.args.get('job_id', type=int)
    if not job_id:
        return jsonify({'error': 'Missing job_id'}), 400

    # ---- Access check ----
    if not (current_user.has_role('admin') or current_user.has_role('manager')):
        driver_job = Job.query.filter_by(driver_id=current_user.driver_id, id=job_id).first()
        if not driver_job:
            return jsonify({'error': 'Forbidden'}), 403

    # Fetch photos
    photos = JobPhoto.query.filter_by(job_id=job_id).all()
    if not photos:
        return jsonify({'message': 'No photos found for this job'}), 404

    # Format response
    photo_list = []
    for photo in photos:
        # Use original filename (stored in photo.filename), NOT the hash-based storage name
        # photo.filename = "54_2_OTS_1762528397.jpg" (for URL)
        # photo.file_path = "images/2025/11/07/4c3cbc9b6eee6be6.jpg" (for storage)
        file_url = url_for('uploaded_file', filename=photo.filename, _external=True)
        photo_list.append({
            'photo_id': photo.id,
            'stage': photo.stage,
            'file_size_kb': photo.file_size,
            'file_size_mb': round(photo.file_size / 1024, 2),  # in MB
            'file_url': file_url,
            'uploaded_at': photo.uploaded_at.isoformat() if photo.uploaded_at else None
        })

    return jsonify({
        'job_id': job_id,
        'photos': photo_list
    }), 200


# ---------------- UPDATE PHOTO CONFIG ----------------
@mobile_driver_bp.route('/admin/photo_config', methods=['POST'])
@auth_required()
@roles_accepted('admin')
def update_photo_config():
    """
    Admin-only: Update Photo Configuration
    - Set per-stage limits (max photos, max size, allowed formats)
    """
    data = request.get_json()
    stage = data.get('stage')
    max_photos = data.get('max_photos')
    max_size_mb = data.get('max_size_mb')
    allowed_formats = data.get('allowed_formats')

    if not stage:
        return jsonify({'error': 'Stage is required'}), 400

    # Upsert config
    config = PhotoConfig.query.filter_by(stage=stage).first()
    if not config:
        config = PhotoConfig(stage=stage)

    if max_photos:
        config.max_photos = int(max_photos)
    if max_size_mb:
        config.max_size_mb = float(max_size_mb)
    if allowed_formats:
        config.allowed_formats = allowed_formats

    db.session.add(config)
    db.session.commit()

    return jsonify({'message': f'PhotoConfig updated for stage {stage}', 'config': {
        'stage': config.stage,
        'max_photos': config.max_photos,
        'max_size_mb': config.max_size_mb,
        'allowed_formats': config.allowed_formats
    }}), 200


# ---------------- GET DRIVER JOBS (TABS) ----------------
@mobile_driver_bp.route("/driver/jobs", methods=["GET"])
@auth_required()
@limiter.limit("1000 per hour")  
def get_driver_jobs():
    """
    Driver Jobs API
    Tabs supported:
    - active   → only "On The Way" jobs
    - today    → jobs scheduled today (closest pickup first)
    - upcoming → future jobs (today after now OR later dates, only new/confirmed)
    - history  → completed jobs (JC) - sorted by completion time (most recent first)
    """
    try:
        driver_id = request.args.get("driver_id", type=int)
        tab = request.args.get("tab", type=str, default="active")
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("pageSize", 10, type=int)

        if not driver_id:
            return jsonify({"error": "driver_id is required"}), 400

        # Base query with eager loading for customer
        # CRITICAL: All queries MUST inherit the is_deleted.is_(False) filter to maintain soft delete contract
        # This ensures deleted jobs are never exposed to mobile drivers
        query = Job.query.options(joinedload(Job.customer)).filter(
            Job.driver_id == driver_id,
            Job.is_deleted.is_(False)
        )

        today_date = date.today().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%H:%M:%S")

        # ---- Tab logic ----
        if tab == "active":
            query = query.filter(Job.status.in_(["otw", "ots", "pob"]))
        elif tab == "today":
            query = query.filter(
                Job.pickup_date == today_date,
                Job.status.in_(["confirmed"])
            ).order_by(Job.pickup_time.asc())
        elif tab == "upcoming":
            query = query.filter(
                db.or_(
                    Job.pickup_date > today_date,
                    db.and_(
                        Job.pickup_date == today_date,
                        Job.pickup_time > now_time
                    )
                )
            ).filter(Job.status.in_(["confirmed"]))

        elif tab == "history":
            query = query.filter(Job.status.in_(["jc", "sd"]))
            # Sort by end_time descending (most recent completed jobs first)
            # If end_time is not available, fall back to updated_at
            query = query.order_by(
                db.case(
                    (Job.end_time.isnot(None), Job.end_time),
                    else_=Job.updated_at
                ).desc()
            )

        else:
            return jsonify({"error": f"Invalid tab: {tab}"}), 400

        # Default ordering
        if tab in ["today", "upcoming"]:
            query = query.order_by(Job.pickup_date.asc(), Job.pickup_time.asc())
        elif tab == "history":
            # History tab ordering is already handled above
            pass
        else:
            query = query.order_by(Job.pickup_date.desc(), Job.pickup_time.desc())

        # Pagination
        jobs = query.paginate(page=page, per_page=page_size, error_out=False)

        # Format response
        job_list = []
        for job in jobs.items:
            job_data = {
                "id": job.id,
                "pickup_date": job.pickup_date,
                "pickup_time": job.pickup_time,
                "status": job.status,
                "pickup_location": job.pickup_location,
                "dropoff_location": job.dropoff_location,
                "passenger_name": job.passenger_name,
                "passenger_mobile": job.passenger_mobile,
                "customer": {
                    "id": getattr(job.customer, 'id', None) if job.customer else None,
                    "name": getattr(job.customer, 'name', None) if job.customer else None
                }
            }
            
            # For history tab, include completion time information
            if tab == "history":
                job_data["end_time"] = job.end_time.isoformat() if job.end_time else None
                job_data["updated_at"] = job.updated_at.isoformat() if job.updated_at else None

            # Include operational billing info for driver app
            job_data["cash_to_collect"] = float(job.cash_to_collect) if getattr(job, 'cash_to_collect', None) is not None else None
            job_data["job_cost"] = float(job.job_cost) if getattr(job, 'job_cost', None) is not None else None

            job_list.append(job_data)

        return jsonify({
            "meta": {
                "page": page,
                "pageSize": page_size,
                "total": jobs.total,
                "pages": jobs.pages
            },
            "data": job_list
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@mobile_driver_bp.route('/driver/jobs/<int:job_id>/update-collection', methods=['PUT'])
@auth_required()
def update_job_collection(job_id: int):
    """Driver can update collected cash for a job.

    Accepts JSON: { "cash_to_collect": 12.5 }
    Only the assigned driver or admin/manager may update.
    """
    data = request.get_json(force=True, silent=True) or {}
    if 'cash_to_collect' not in data:
        return jsonify({'error': 'cash_to_collect is required'}), 400

    # All DB operations wrapped to ensure rollback on failure
    try:
        cash_val = float(data.get('cash_to_collect'))
    except (TypeError, ValueError):
        return jsonify({'error': 'cash_to_collect must be a valid number'}), 400

    # Range validation
    if cash_val < 0:
        return jsonify({'error': 'cash_to_collect cannot be negative'}), 400
    if cash_val > 100000:
        return jsonify({'error': 'cash_to_collect exceeds maximum allowed'}), 400

    try:
        job = Job.query.get(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404

        # Authorization: assigned driver, contractor's driver, or admin/manager
        is_assigned_driver = current_user.driver_id == job.driver_id
        is_contractor_driver = False
        if job.contractor_id and current_user.driver_id:
            from backend.models.contractor import Contractor
            contractor = Contractor.query.get(job.contractor_id)
            if contractor:
                # Contractor.drivers relationship may be a list of Driver objects
                try:
                    contractor_driver_ids = [d.id for d in getattr(contractor, 'drivers', []) if hasattr(d, 'id')]
                except Exception:
                    contractor_driver_ids = []
                if current_user.driver_id in contractor_driver_ids:
                    is_contractor_driver = True

        if not (current_user.has_role('admin') or current_user.has_role('manager') or is_assigned_driver or is_contractor_driver):
            return jsonify({'error': 'Forbidden'}), 403

        job.cash_to_collect = cash_val
        db.session.add(job)
        db.session.commit()
    except (TypeError, ValueError):
        db.session.rollback()
        return jsonify({'error': 'cash_to_collect must be a valid number'}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"Failed to update job collection for job {job_id}: {e}", exc_info=True)
        return jsonify({'error': 'Failed to update job collection', 'details': str(e)}), 500

    # Build response payload (mirror GET /driver/jobs item)
    job_data = {
        "id": job.id,
        "pickup_date": job.pickup_date,
        "pickup_time": job.pickup_time,
        "status": job.status,
        "pickup_location": job.pickup_location,
        "dropoff_location": job.dropoff_location,
        "passenger_name": job.passenger_name,
        "passenger_mobile": job.passenger_mobile,
        "customer": {
            "id": getattr(job.customer, 'id', None) if job.customer else None,
            "name": getattr(job.customer, 'name', None) if job.customer else None
        },
        "cash_to_collect": float(job.cash_to_collect) if job.cash_to_collect is not None else None,
        "job_cost": float(job.job_cost) if getattr(job, 'job_cost', None) is not None else None
    }

    if job.end_time:
        job_data['end_time'] = job.end_time.isoformat()
    if job.updated_at:
        job_data['updated_at'] = job.updated_at.isoformat()

    return jsonify(job_data), 200


# ---------------- DRIVER ALERTS ----------------
@mobile_driver_bp.route('/driver/alerts', methods=['GET'])
@auth_required()
@roles_accepted('driver')
def get_driver_alerts():
    """
    Get active delayed trip alerts for the logged-in driver.
    Returns alerts with job details, elapsed time, and actions.
    """
    try:
        driver_id = current_user.driver_id
        if not driver_id:
            return jsonify({'error': 'Driver not authenticated'}), 403
        
        # Get active alerts for this driver
        alerts = JobMonitoringAlert.query.filter(
            JobMonitoringAlert.driver_id == driver_id,
            JobMonitoringAlert.status == 'active'
        ).all()
        
        # Preload all jobs referenced by the alerts to avoid N+1 queries
        job_ids = {alert.job_id for alert in alerts if alert.job_id}
        jobs_by_id = {}
        if job_ids:
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            jobs_by_id = {job.id: job for job in jobs}
        
        alert_list = []
        for alert in alerts:
            job = jobs_by_id.get(alert.job_id)
            if job:
                # Calculate elapsed time since pickup_time
                elapsed_minutes = None
                if job.pickup_date and job.pickup_time:
                    pickup_str = f"{job.pickup_date} {job.pickup_time}"
                    try:
                        pickup_datetime = parse(pickup_str)
                        # If the parsed datetime doesn't have timezone info, assume it's local time
                        if pickup_datetime.tzinfo is None:
                            # Use local timezone (assumes the pickup time is in local time, not UTC)
                            local_tz = pytz.timezone('Asia/Singapore')  # Assuming Singapore timezone
                            pickup_datetime = local_tz.localize(pickup_datetime)
                            # Convert to UTC for comparison
                            pickup_datetime = pickup_datetime.astimezone(pytz.UTC)
                        else:
                            # If timezone info exists, convert to UTC for comparison
                            pickup_datetime = pickup_datetime.astimezone(pytz.UTC)
                        
                        current_time = datetime.now(pytz.UTC)
                        elapsed_seconds = (current_time - pickup_datetime).total_seconds()
                        elapsed_minutes = int(elapsed_seconds / 60)
                    except Exception as e:
                        logging.error(f"Failed to calculate elapsed time for job {job.id}: {e}")
                
                # Convert alert created_at to Singapore timezone for consistent display
                singapore_tz = pytz.timezone('Asia/Singapore')
                created_at_sg = alert.created_at.astimezone(singapore_tz) if alert.created_at.tzinfo else alert.created_at.replace(tzinfo=pytz.UTC).astimezone(singapore_tz)
                
                alert_list.append({
                    'id': alert.id,
                    'job_id': job.id,
                    'job_id_display': f"#{job.id}",
                    'passenger_name': job.passenger_name,
                    'pickup_location': job.pickup_location,
                    'delay_minutes': elapsed_minutes,  # Delay in minutes since pickup time
                    'pickup_datetime_formatted': f"{job.pickup_date} {job.pickup_time}",  # Combined pickup date and time
                    'elapsed_minutes': elapsed_minutes,
                    'reminder_count': alert.reminder_count,
                    'created_at': created_at_sg.isoformat(),
                    'actions': [
                        {'type': 'view_start_trip', 'label': 'View & Start Trip'},
                        {'type': 'acknowledge', 'label': 'Acknowledge'}
                    ]
                })
        
        # Get alert count for badge
        alert_count = len(alert_list)
        
        # Use Singapore timezone for the response timestamp
        singapore_tz = pytz.timezone('Asia/Singapore')
        timestamp_sg = datetime.now(singapore_tz)
        
        return jsonify({
            'alerts': alert_list,
            'alert_count': alert_count,
            'timestamp': timestamp_sg.isoformat()
        }), 200
        
    except Exception as e:
        logging.error(f"Error fetching driver alerts: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while fetching alerts'}), 500


@mobile_driver_bp.route('/driver/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@auth_required()
@roles_accepted('driver')
def acknowledge_driver_alert(alert_id):
    """
    Acknowledge a specific alert, removing it from active alerts.
    """
    try:
        driver_id = current_user.driver_id
        if not driver_id:
            return jsonify({'error': 'Driver not authenticated'}), 403
        
        # Get the alert and verify it belongs to the driver
        alert = JobMonitoringAlert.query.filter(
            JobMonitoringAlert.id == alert_id,
            JobMonitoringAlert.driver_id == driver_id,
            JobMonitoringAlert.status == 'active'
        ).first()
        
        if not alert:
            return jsonify({'error': 'Alert not found or already acknowledged'}), 404
        
        # Acknowledge the alert
        success = JobMonitoringAlert.acknowledge_alert(alert_id)
        
        if success:
            return jsonify({
                'message': 'Alert acknowledged successfully',
                'alert_id': alert_id
            }), 200
        else:
            return jsonify({'error': 'Failed to acknowledge alert'}), 500
            
    except Exception as e:
        logging.error(f"Error acknowledging driver alert: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while acknowledging alert'}), 500


@mobile_driver_bp.route('/driver/push-notification-token', methods=['POST'])
@auth_required()
@roles_accepted('driver')
def update_push_notification_token():
    """
    Update the driver's push notification token.
    """
    try:
        driver_id = current_user.driver_id
        if not driver_id:
            return jsonify({'error': 'Driver not authenticated'}), 403
        
        data = request.get_json()
        token = data.get('token')
        platform = data.get('platform', 'android')  # 'android' or 'ios'
        
        if not token:
            return jsonify({'error': 'Push notification token is required'}), 400
        
        # Update the user's device token
        user = User.query.filter_by(driver_id=driver_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if platform.lower() == 'ios':
            user.ios_device_token = token
        else:
            user.android_device_token = token
        
        db.session.commit()
        
        return jsonify({
            'message': 'Push notification token updated successfully',
            'platform': platform
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating push notification token: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while updating token'}), 500


@mobile_driver_bp.route('/driver/jobs/<int:job_id>/start-trip', methods=['POST'])
@auth_required()
@roles_accepted('driver')
def start_trip_from_alert(job_id):
    """
    Start a trip directly from an alert, updating job status to OTW.
    """
    try:
        driver_id = current_user.driver_id
        if not driver_id:
            return jsonify({'error': 'Driver not authenticated'}), 403
        
        # Get the job and verify it belongs to the driver
        job = Job.query.filter_by(id=job_id, driver_id=driver_id).first()
        if not job:
            return jsonify({'error': 'Job not found or not assigned to this driver'}), 404
        
        # Check if job can transition to OTW
        if not job.can_transition_to(JobStatus.OTW.value):
            return jsonify({
                'error': f'Job cannot transition from {job.status} to {JobStatus.OTW.value}'
            }), 400
        
        # Store old status for audit
        old_status = job.status
        import pytz
        singapore_tz = pytz.timezone('Asia/Singapore')
        job.status = JobStatus.OTW.value
        job.updated_at = datetime.now(singapore_tz).astimezone(pytz.UTC)
        
        # Set start_time if not already set
        if job.start_time is None:
            job.start_time = datetime.now(singapore_tz).astimezone(pytz.UTC)
        
        # Clear any monitoring alerts for this job
        JobMonitoringAlert.clear_alert(job_id)
        
        # Create audit record
        from backend.models.job_audit import JobAudit
        audit = JobAudit(
            job_id=job.id,
            old_status=old_status,
            new_status=JobStatus.OTW.value,
            changed_by=current_user.id if hasattr(request, 'user') and request.user else None
        )
        db.session.add(audit)
        
        db.session.commit()
        
        # Send push notification to driver if available
        try:
            if job.driver_id:
                driver = DriverService.get_by_id(job.driver_id)
                if driver:
                    user = User.query.filter_by(driver_id=driver.id).first()
                    if user:
                        for token in [user.android_device_token, user.ios_device_token]:
                            if token:
                                PushNotificationService.send(
                                    token=token,
                                    title="Trip Started",
                                    body=f"Job #{job.id} status updated to On The Way",
                                    data={"job_id": str(job.id), "status": "otw"}
                                )
        except Exception as e:
            logging.warning(f"Failed to send push notification for job {job.id}: {e}")
        
        return jsonify({
            'message': 'Trip started successfully',
            'job_id': job_id,
            'old_status': old_status,
            'new_status': JobStatus.OTW.value
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error starting trip from alert: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while starting trip'}), 500


@mobile_driver_bp.route('/driver/alerts/history', methods=['GET'])
@auth_required()
@roles_accepted('driver')
def get_driver_alert_history():
    """
    Get alert history for the logged-in driver (acknowledged/cleared alerts within 24 hours).
    """
    from datetime import timedelta  # Import timedelta locally
    try:
        driver_id = current_user.driver_id
        if not driver_id:
            return jsonify({'error': 'Driver not authenticated'}), 403
        
        # Get alert history for this driver (acknowledged/cleared within last 24 hours)
        cutoff_time = datetime.now(pytz.UTC) - timedelta(hours=24)
        
        # Query that handles both acknowledged_at and cleared_at timestamps
        from sqlalchemy import and_, or_
        alerts = JobMonitoringAlert.query.filter(
            JobMonitoringAlert.driver_id == driver_id,
            JobMonitoringAlert.status.in_(['acknowledged', 'cleared']),
            or_(
                and_(JobMonitoringAlert.status == 'acknowledged', JobMonitoringAlert.acknowledged_at >= cutoff_time),
                and_(JobMonitoringAlert.status == 'cleared', JobMonitoringAlert.cleared_at >= cutoff_time)
            )
        ).order_by(JobMonitoringAlert.created_at.desc()).limit(50).all()
        
        # Preload all jobs referenced by the alerts to avoid N+1 queries
        job_ids = {alert.job_id for alert in alerts if alert.job_id}
        jobs_by_id = {}
        if job_ids:
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            jobs_by_id = {job.id: job for job in jobs}
        
        alert_history = []
        for alert in alerts:
            job = jobs_by_id.get(alert.job_id)
            if job:
                # Determine action taken based on status
                action_taken = 'acknowledged' if alert.status == 'acknowledged' else 'auto-cleared'
                timestamp = alert.acknowledged_at if alert.status == 'acknowledged' else alert.cleared_at
                
                # Convert all datetime objects to Singapore timezone for consistent display
                singapore_tz = pytz.timezone('Asia/Singapore')
                alert_time_sg = alert.created_at.astimezone(singapore_tz) if alert.created_at.tzinfo else alert.created_at.replace(tzinfo=pytz.UTC).astimezone(singapore_tz)
                
                if timestamp:
                    if timestamp.tzinfo:
                        action_timestamp_sg = timestamp.astimezone(singapore_tz)
                    else:
                        action_timestamp_sg = timestamp.replace(tzinfo=pytz.UTC).astimezone(singapore_tz)
                else:
                    action_timestamp_sg = None
                
                alert_history.append({
                    'id': alert.id,
                    'job_id': job.id,
                    'job_id_display': f"#{job.id}",
                    'passenger_name': job.passenger_name,
                    'pickup_location': job.pickup_location,
                    'alert_time': alert_time_sg.isoformat(),
                    'action_taken': action_taken,
                    'action_timestamp': action_timestamp_sg.isoformat() if action_timestamp_sg else None,
                    'reminder_count': alert.reminder_count
                })
        
        # Use Singapore timezone for the response timestamp
        singapore_tz = pytz.timezone('Asia/Singapore')
        timestamp_sg = datetime.now(singapore_tz)
        
        return jsonify({
            'alert_history': alert_history,
            'total_count': len(alert_history),
            'timestamp': timestamp_sg.isoformat()
        }), 200
        
    except Exception as e:
        logging.error(f"Error fetching driver alert history: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while fetching alert history'}), 500


@mobile_driver_bp.route('/driver/jobs-with-alerts', methods=['GET'])
@auth_required()
@roles_accepted('driver')
def get_jobs_with_alerts():
    """
    Get jobs with active alerts for the logged-in driver.
    Used to show visual indicators on job cards.
    """
    try:
        driver_id = current_user.driver_id
        if not driver_id:
            return jsonify({'error': 'Driver not authenticated'}), 403
        
        # Get active alerts for this driver
        active_alerts = JobMonitoringAlert.query.filter(
            JobMonitoringAlert.driver_id == driver_id,
            JobMonitoringAlert.status == 'active'
        ).all()
        
        # Extract job IDs that have alerts
        alert_job_ids = [alert.job_id for alert in active_alerts]
        
        # Preload all jobs referenced by the alerts to avoid N+1 queries
        job_ids = {alert.job_id for alert in active_alerts if alert.job_id}
        jobs_by_id = {}
        if job_ids:
            jobs = Job.query.filter(Job.id.in_(job_ids)).all()
            jobs_by_id = {job.id: job for job in jobs}
        
        # Get job details for these alerts
        jobs_with_alerts = []
        for alert in active_alerts:
            job = jobs_by_id.get(alert.job_id)
            if job:
                # Calculate elapsed time since pickup_time
                elapsed_minutes = None
                if job.pickup_date and job.pickup_time:
                    pickup_str = f"{job.pickup_date} {job.pickup_time}"
                    try:
                        pickup_datetime = parse(pickup_str)
                        # If the parsed datetime doesn't have timezone info, assume it's local time
                        if pickup_datetime.tzinfo is None:
                            # Use local timezone (assumes the pickup time is in local time, not UTC)
                            local_tz = pytz.timezone('Asia/Singapore')  # Assuming Singapore timezone
                            pickup_datetime = local_tz.localize(pickup_datetime)
                            # Convert to UTC for comparison
                            pickup_datetime = pickup_datetime.astimezone(pytz.UTC)
                        
                        current_time = datetime.now(pytz.UTC)
                        elapsed_seconds = (current_time - pickup_datetime).total_seconds()
                        elapsed_minutes = int(elapsed_seconds / 60)
                    except Exception as e:
                        logging.error(f"Failed to calculate elapsed time for job {job.id}: {e}")
                
                # Convert alert created_at to Singapore timezone for consistent display
                singapore_tz = pytz.timezone('Asia/Singapore')
                alert_created_at_sg = alert.created_at.astimezone(singapore_tz) if alert.created_at.tzinfo else alert.created_at.replace(tzinfo=pytz.UTC).astimezone(singapore_tz)
                
                jobs_with_alerts.append({
                    'job_id': job.id,
                    'job_id_display': f"#{job.id}",
                    'passenger_name': job.passenger_name,
                    'pickup_location': job.pickup_location,
                    'delay_minutes': elapsed_minutes,  # Delay in minutes since pickup time
                    'pickup_datetime_formatted': f"{job.pickup_date} {job.pickup_time}",  # Combined pickup date and time
                    'pickup_time': job.pickup_time,
                    'elapsed_minutes': elapsed_minutes,
                    'reminder_count': alert.reminder_count,
                    'alert_created_at': alert_created_at_sg.isoformat()
                })
        
        # Use Singapore timezone for the response timestamp
        singapore_tz = pytz.timezone('Asia/Singapore')
        timestamp_sg = datetime.now(singapore_tz)
        
        return jsonify({
            'jobs_with_alerts': jobs_with_alerts,
            'alert_job_ids': alert_job_ids,
            'alert_count': len(alert_job_ids),
            'timestamp': timestamp_sg.isoformat()
        }), 200
        
    except Exception as e:
        logging.error(f"Error fetching jobs with alerts: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while fetching jobs with alerts'}), 500
