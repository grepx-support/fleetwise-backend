from flask import Blueprint, jsonify
from services.driver_scoring import get_job_data, compute_driver_scores, get_best_driver
import time
from flask_security.decorators import roles_accepted, auth_required

pipeline_bp = Blueprint('pipeline', __name__)

@pipeline_bp.route('/run', methods=['GET'])
@roles_accepted('admin', 'manager', 'accountant', 'customer')
def run_pipeline():
    try:
        start = time.time()
        df = get_job_data()
        ranking = compute_driver_scores(df)
        print(ranking)
        best_driver = get_best_driver(ranking)

        ai_result = {
            "status": "ok",
            "best_driver": best_driver,
            "ranking": ranking
        }
        end = time.time()
        print(f"Time taken: {end - start:.4f} seconds")

        return jsonify(ai_result), 200

    except Exception as e:
        print("Error:", e)
        return jsonify({'error': 'Something Failed'}), 500
