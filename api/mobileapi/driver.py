from backend.services.driver_service import DriverService
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
    - Returns all remarks in response
    - Retries in case of DB lock issues
    """
    data = request.get_json()

    driver_id = data.get('driver_id')
    job_id = data.get('job_id')
    new_status = data.get('status')
    remark_text = data.get('remark')   # NEW: optional remark



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

            # Case 1: Status already set → still allow new remark
            if job.status == new_status:
                # Only create audit record if a remark is being added
                if remark_text:
                    audit_record = JobAudit(
                        job_id=job.id,
                        changed_by=current_user.id,  # Always valid due to @auth_required()
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
                    'message': 'Status already set' if not remark_text else 'Remark added',
                    'job_id': job.id,
                    'status': job.status,
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
            if new_status in [JobStatus.JC.value, JobStatus.SD.value]:
                if job.end_time is None:
                    job.end_time = datetime.now(timezone.utc)
            
            # Create audit record for status change
            audit_record = JobAudit(
                job_id=job.id,
                changed_by=current_user.id,  # Always valid due to @auth_required()
                old_status=old_status,
                new_status=new_status,
                reason='Status updated via Driver API'
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

    try:
        with open(file_path, 'wb') as f:
            f.write(img_io.getbuffer())

        job_photo = JobPhoto(
            job_id=job_id,
            driver_id=driver_id,
            stage=stage,
            file_path=file_path,
            file_size=os.path.getsize(file_path) // 1024,
            file_hash=file_hash,   # store hash in DB
            filename=filename      # store filename for indexed lookups
        )
        db.session.add(job_photo)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        if os.path.exists(file_path):
            os.remove(file_path)  # cleanup orphan file
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

    # Return file URL
    file_url = url_for('uploaded_file', filename=filename, _external=True)
    return jsonify({
        'message': 'Photo uploaded successfully',
        'photo_id': job_photo.id,
        'file_path': file_path,
        'file_url': file_url
    }), 201


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
        filename = os.path.basename(photo.file_path)
        file_url = url_for('uploaded_file', filename=filename, _external=True)
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
        query = Job.query.options(joinedload(Job.customer)).filter(Job.driver_id == driver_id)

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
                    Job.pickup_date > today_date
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
