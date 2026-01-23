import os
import sys

# Change to the project root directory
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.environ.get("PROJECT_ROOT", script_dir)
os.chdir(project_root)

# Add project root to Python path
sys.path.insert(0, project_root)

try:
    print("Setting up Flask application context...")
    
    # Import the app properly
    from backend.server import app
    from backend.services.scheduler_service import scheduler_service
    
    print("Starting job monitoring scan...")
    
    # Run the monitoring function
    with app.app_context():
        scheduler_service.monitor_overdue_jobs()
    
    print("✅ Job monitoring completed successfully!")
    print("You can now check your alerts API endpoint for results.")
    
except Exception as e:
    print(f"❌ Error occurred: {e}")
    import traceback
    traceback.print_exc()