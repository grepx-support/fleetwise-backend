from flask import Blueprint, request, jsonify
from pathlib import Path
import pandas as pd
from orangeworkflow.runner import upload_and_run, compute_md5
from backend.models import Driver  # import your model
import threading
import fcntl

ai_pipeline_routes_bp = Blueprint("ai_pipeline_routes_bp", __name__)

@ai_pipeline_routes_bp.route("/ai_suggest_driver", methods=["POST"])
def ai_suggest_driver():
    """
    Run the driver recommendation workflow and return the top-ranked driver,
    enriched with data from the Driver model.
    """
    try:
        data = request.get_json(force=True) if request.is_json else {}
        allowed_data_dir = Path("backend/data").resolve()
        default_csv = allowed_data_dir / "jobs.csv"

        # Reject custom paths outright
        if "csv_path" in data:
            return jsonify({
                "status": "error",
                "message": "Custom csv_path not allowed."
            }), 400

        csv_path = default_csv

        # Double-check the file resides under the allowed directory
        if not str(csv_path).startswith(str(allowed_data_dir)):
            return jsonify({
                "status": "error",
                "message": "Invalid CSV path."
            }), 400
        csv_path = Path(csv_path).resolve()

        # Define output directory
        output_dir = Path.cwd() / "outputs" / "driver_recommendation_output"
        meta_file = output_dir / ".last_run_meta"
        lock_file = output_dir / ".workflow_lock"
        lock_file.touch(exist_ok=True)
        with open(lock_file, 'w') as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                current_hash = compute_md5(csv_path)
                previous_hash = meta_file.read_text().strip() if meta_file.exists() else None
                if current_hash != previous_hash:
                    def run_in_background():
                        try:
                            print("⚙️ Running workflow in background...")
                            upload_and_run(csv_path, workflow_name="driver_recommendation_system")
                            meta_file.write_text(current_hash)
                            print("✅ Workflow completed.")
                        except Exception as e:
                            print(f"❌ Workflow failed: {e}")
                    threading.Thread(target=run_in_background, daemon=False).start()
                    return jsonify({"status": "processing", "message": "Workflow started"}), 202
            except IOError:
                return jsonify({"status": "processing", "message": "Workflow already running"}), 202
        # Otherwise, reuse cached output
        output_files = list(output_dir.glob("*.csv"))
        if not output_files:
            return jsonify({"status": "error", "message": "No output CSV found"}), 404
        if len(output_files) > 1:
            return jsonify({"status": "error", "message": "Multiple output files found"}), 500

        df = pd.read_csv(output_files[0])
        required_cols = ["rank", "driver_id"]
        if df.empty or not all(col in df.columns for col in required_cols):
            return jsonify({"status": "error", "message": "Invalid output format"}), 400

        # Sort and find top driver
        df = df.sort_values("rank")
        top_driver_id = int(df.iloc[0]["driver_id"])

        # Enrich with driver name
        ranked = df.to_dict(orient="records")
        driver_ids = [int(r["driver_id"]) for r in ranked]
        drivers = Driver.query_active().filter(Driver.id.in_(driver_ids)).all()
        driver_map = {d.id: d.name for d in drivers}
        for r in ranked:
            r["name"] = driver_map.get(int(r["driver_id"]), f"Driver {r['driver_id']}")

        best_driver = next((r for r in ranked if r["driver_id"] == top_driver_id), None)

        return jsonify({
            "status": "ok",
            "best_driver_id": top_driver_id,
            "best_driver": best_driver,
            "ranking": ranked
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
