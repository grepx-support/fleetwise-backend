from flask import Blueprint, request, jsonify
from pathlib import Path
import pandas as pd
from orangeworkflow.runner import upload_and_run, compute_md5
from backend.models import Driver  # import your model
import threading

ai_pipeline_routes_bp = Blueprint("ai_pipeline_routes_bp", __name__)

@ai_pipeline_routes_bp.route("/ai_suggest_driver", methods=["POST"])
def ai_suggest_driver():
    """
    Run the driver recommendation workflow and return the top-ranked driver,
    enriched with data from the Driver model.
    """
    try:
        data = request.get_json(force=True) if request.is_json else {}
        csv_path = data.get("csv_path", "backend/data/jobs.csv")
        csv_path = Path(csv_path).resolve()

        # Define output directory
        output_dir = Path.cwd() / "outputs" / "driver_recommendation_output"
        meta_file = output_dir / ".last_run_meta"
        current_hash = compute_md5(csv_path)
        previous_hash = meta_file.read_text().strip() if meta_file.exists() else None

        # If new data is detected, start async workflow
        if current_hash != previous_hash:
            def run_in_background():
                print("⚙️ Running workflow in background (new data detected)...")
                upload_and_run(csv_path, workflow_name="driver_recommendation_system")
                print("✅ Workflow completed.")

            threading.Thread(target=run_in_background, daemon=True).start()

            return jsonify({
                "status": "processing",
                "message": "Workflow running in background. Please retry shortly."
            }), 202

        # Otherwise, reuse cached output
        output_files = list(output_dir.glob("*.csv"))
        if not output_files:
            return jsonify({"status": "error", "message": "No output CSV found"}), 404

        df = pd.read_csv(output_files[0])
        if df.empty:
            return jsonify({"status": "error", "message": "Output CSV is empty"}), 400

        # Sort and find top driver
        df = df.sort_values("rank")
        top_driver_id = int(df.iloc[0]["driver_id"])

        # Enrich with driver name
        ranked = df.to_dict(orient="records")
        for r in ranked:
            driver = Driver.query_active().filter_by(id=int(r["driver_id"])).first()
            r["name"] = driver.name if driver else f"Driver {r['driver_id']}"

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
