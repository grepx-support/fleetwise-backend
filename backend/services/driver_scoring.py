import sqlite3
import pandas as pd
from flask import current_app

SUCCESS_STATUSES = {"jc", "confirmed", "otw", "ots", "pob", "sd"}
CANCEL_STATUS = "canceled"

def get_dbpath():
    """Safely get DB path from current Flask app context."""
    return current_app.config.get("DB_PATH")

def get_job_data():
    """Fetches job data from the database."""
    DBPATH = get_dbpath()
    conn = sqlite3.connect(DBPATH)
    df = pd.read_sql_query("SELECT driver_id, status FROM job", conn)
    conn.close()
    return df

def compute_driver_scores(df: pd.DataFrame):
    """Computes success, canceled, total jobs, and success ratio per driver."""
    if df.empty:
        return []

    results = []
    for driver_id, group in df.groupby("driver_id"):
        total = len(group)
        success = group["status"].isin(SUCCESS_STATUSES).sum()
        canceled = (group["status"] == CANCEL_STATUS).sum()
        ratio = success / total if total else 0

        results.append({
            "driver_id": driver_id,
            "total_jobs": total,
            "success": int(success),
            "canceled": int(canceled),
            "ratio": round(ratio, 2)
        })

    # Sort by success ratio descending
    return sorted(results, key=lambda x: x["ratio"], reverse=True)

def get_best_driver(ranking):
    """Returns the top driver from the ranking."""
    if not ranking:
        return None
    top = ranking[0]
    return {"driver_id": top["driver_id"], "name": f"Driver {top['driver_id']}"}
