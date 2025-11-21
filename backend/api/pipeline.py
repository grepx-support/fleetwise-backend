from flask import Blueprint, jsonify
from services.driver_scoring import get_job_data, compute_driver_scores, get_best_driver
import time
from flask_security.decorators import roles_accepted
import logging
from flask import current_app
import traceback

pipeline_bp = Blueprint('pipeline', __name__)

@pipeline_bp.route('/run', methods=['POST'])
@roles_accepted('admin', 'manager', 'accountant', 'customer')
def run_pipeline():
    try:
        start = time.time()

        # 1️⃣ Fetch all job data without any filters
        df = get_job_data()  # fetch all jobs

        # 2️⃣ Compute driver scoring
        ranking = compute_driver_scores(df)
        best = get_best_driver(ranking)

        end = time.time()

        return jsonify({
            "success": True,
            "processing_time": round(end - start, 3),
            "ranking": ranking,
            "best_driver": best
        }), 200

    except Exception as e:
       logging.error(f"Pipeline failed: {str(e)}", extra={
           "traceback": traceback.format_exc()
       })
       return jsonify({
           'error': 'Driver recommendation failed',
           'details': str(e) if current_app.debug else None
       }), 500