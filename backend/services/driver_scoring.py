import sqlite3
import pandas as pd
from flask import current_app

SUCCESS_STATUSES = {"jc", "confirmed", "otw", "ots", "pob", "sd"}
CANCEL_STATUS = "canceled"

def get_dbpath():
    """Safely get DB path from current Flask app context."""
    return current_app.config.get("DB_PATH")

def get_job_data():
    DBPATH = get_dbpath()
    query = """
        SELECT 
            d.id AS driver_id,
            d.name AS driver_name,
            j.status
        FROM driver d
        LEFT JOIN job j ON d.id = j.driver_id
        WHERE d.is_deleted = 0 AND d.status = 'Active'
    """
    with sqlite3.connect(DBPATH) as conn:
        df = pd.read_sql_query(query, conn)
    return df

def compute_driver_scores(df: pd.DataFrame):
    DBPATH = get_dbpath()

    # Fallback if df is empty or all jobs missing
    if df.empty:
        with sqlite3.connect(DBPATH) as conn:
            drivers = pd.read_sql_query(
                "SELECT id as driver_id, name FROM driver WHERE is_deleted = 0 AND status = 'Active'",
                conn
            )
        return [
            {"driver_id": row.driver_id, "name": row.name, "total_jobs": 0, "success": 0, "canceled": 0, "ratio": 0.0}
            for _, row in drivers.iterrows()
        ]

    results = []
    for driver_id, group in df.groupby("driver_id"):
        name = group["driver_name"].iloc[0] if not group.empty and pd.notnull(group["driver_name"].iloc[0]) else "Unknown"
        total = len(group.dropna(subset=["status"]))
        success = group["status"].isin(SUCCESS_STATUSES).sum() if total else 0
        canceled = (group["status"] == CANCEL_STATUS).sum() if total else 0
        ratio = success / total if total else 0.0

        results.append({
            "driver_id": driver_id,
            "name": name,
            "total_jobs": total,
            "success": int(success),
            "canceled": int(canceled),
            "ratio": round(ratio, 2)
        })

    # Sort by success ratio descending
    return sorted(results, key=lambda x: x["ratio"], reverse=True)

def get_best_driver(ranking):
    if not ranking:
        return None
    top = ranking[0]
    return {"driver_id": top["driver_id"], "name": top["name"]}
