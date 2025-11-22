from flask import Blueprint, jsonify
from services.driver_scoring import get_job_data, compute_driver_scores, get_best_driver, get_available_driver
import time
from flask_security.decorators import roles_accepted
import logging
from flask import current_app
import traceback

pipeline_bp = Blueprint('pipeline', __name__)
from flask import request

@pipeline_bp.route('/run', methods=['POST'])
@roles_accepted('admin', 'manager', 'accountant', 'customer')
def run_pipeline():
    try:
        start = time.time()

        # Expect pickup date and time in request payload
        data = request.get_json()
        pickup_date = data.get('pickup_date')
        pickup_time = data.get('pickup_time')

        if not pickup_date or not pickup_time:
            return jsonify({'error': 'pickup_date and pickup_time are required'}), 400
        df = get_job_data()

        ranking = compute_driver_scores(df)

        best_driver = get_available_driver(ranking, pickup_date, pickup_time)

        end = time.time()

        return jsonify({
            "success": True,
            "processing_time": round(end - start, 3),
            "ranking": ranking,
            "best_driver": best_driver,
            "message": "Top priority driver had conflict, next available driver suggested." if best_driver != ranking[0] else None
        }), 200

    except Exception as e:
       logging.error(f"Pipeline failed: {str(e)}", extra={
           "traceback": traceback.format_exc()
       })
       return jsonify({
           'error': 'Driver recommendation failed',
           'details': str(e) if current_app.debug else None
       }), 500