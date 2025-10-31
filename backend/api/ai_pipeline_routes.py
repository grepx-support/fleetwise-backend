from flask import Blueprint, request, jsonify
from pathlib import Path
import pandas as pd
from orangeworkflow.runner import upload_and_run, compute_md5
from backend.models import Driver
import threading
import fcntl

ai_pipeline_routes_bp = Blueprint("ai_pipeline_routes_bp", __name__)

ALLOWED_DATA_DIR = Path("backend/data").resolve()
OUTPUT_DIR = Path.cwd() / "outputs" / "driver_recommendation_output"

def validate_csv_path(data):
    csv_path = ALLOWED_DATA_DIR / "jobs.csv"
    if not csv_path.exists():
        raise FileNotFoundError("jobs.csv not found.")
    if not str(csv_path).startswith(str(ALLOWED_DATA_DIR)):
        raise PermissionError("Invalid CSV path.")
    return csv_path

def run_workflow_async(csv_path, meta_file):
    def background():
        try:
            print("⚙️ Running workflow in background...")
            upload_and_run(csv_path, workflow_name="driver_recommendation_system")
            meta_file.write_text(compute_md5(csv_path))
            print("✅ Workflow completed.")
        except Exception as e:
            print(f"❌ Workflow failed: {e}")
    threading.Thread(target=background, daemon=True).start()

def read_workflow_output():
    output_files = list(OUTPUT_DIR.glob("*.csv"))
    if not output_files:
        raise FileNotFoundError("No output CSV found.")
    if len(output_files) > 1:
        raise RuntimeError("Multiple output files found.")
    df = pd.read_csv(output_files[0])
    if df.empty:
        raise ValueError("Empty output file.")
    return df

def enrich_driver_data(df):
    driver_ids = [int(r["driver_id"]) for r in df.to_dict(orient="records")]
    drivers = Driver.query_active().filter(Driver.id.in_(driver_ids)).all()
    driver_map = {d.id: d.name for d in drivers}
    df["name"] = df["driver_id"].apply(lambda x: driver_map.get(int(x), f"Driver {x}"))
    return df

@ai_pipeline_routes_bp.route("/ai_suggest_driver", methods=["POST"])
def ai_suggest_driver():
    try:
        data = request.get_json(force=True) if request.is_json else {}
        csv_path = validate_csv_path(data)
        meta_file = OUTPUT_DIR / ".last_run_meta"
        lock_file = OUTPUT_DIR / ".workflow_lock"
        lock_file.touch(exist_ok=True)

        with open(lock_file, 'w') as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError:
                return jsonify({"status": "processing", "message": "Workflow already running"}), 202

            current_hash = compute_md5(csv_path)
            previous_hash = meta_file.read_text().strip() if meta_file.exists() else None

            if current_hash != previous_hash:
                run_workflow_async(csv_path, meta_file)
                return jsonify({"status": "processing", "message": "Workflow started"}), 202

        df = read_workflow_output()
        df = enrich_driver_data(df)

        ranked = df.to_dict(orient="records")
        return jsonify({"status": "ok", "ranking": ranked})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
