import sys
import os
import uuid
from flask import Blueprint, jsonify, request, send_file, url_for
import pandas as pd
import sqlite3
import tempfile
from datetime import datetime, timedelta
import io
import threading
import logging

# Add the current directory to Python path to fix import issues
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from flask import Blueprint, jsonify, request, send_file
import pandas as pd
import sqlite3
import tempfile
import os

# Try to import auth_required from flask_security.decorators
try:
    from flask_security.decorators import auth_required, roles_required
except ImportError:
    try:
        from flask_security.decorators import auth_required, roles_required
    except ImportError:
        # Fallback implementation if flask_security is not available
        def auth_required():
            def decorator(f):
                def wrapper(*args, **kwargs):
                    return jsonify({'error': 'Authentication system unavailable'}), 503
                return wrapper
            return decorator
        def roles_required(*roles):
            def decorator(f):
                def wrapper(*args, **kwargs):
                    try:
                        from flask_security import current_user
                        if not current_user.is_authenticated:
                            return jsonify({'error': 'Authentication required'}), 401
                        user_roles = [role.name for role in current_user.roles] if hasattr(current_user, 'roles') else []
                        if not any(role in user_roles for role in roles):
                            return jsonify({'error': 'Insufficient permissions'}), 403
                        return f(*args, **kwargs)
                    except ImportError:
                        # If we can't import flask_security, deny access for security
                        return jsonify({'error': 'Authentication system unavailable'}), 503
                return wrapper
            return decorator

# Try to import with different paths
try:
    from backend.extensions import db
    from backend.config import DevConfig
except ImportError:
    try:
        from extensions import db
        from config import DevConfig
    except ImportError:
        # If all else fails, define what we need directly
        class DevConfig:
            BASEDIR = os.path.dirname(os.path.abspath(__file__))
            DB_PATH = os.path.join(BASEDIR, '..', 'app.db')

# For type checking purposes, we'll use a generic type
try:
    from backend.config import DevConfig
    DevConfigType = DevConfig
except ImportError:
    try:
        from config import DevConfig
        DevConfigType = DevConfig
    except ImportError:
        DevConfigType = DevConfig

db_export_bp = Blueprint('db_export', __name__)

# Store for generated files (in production, use a proper storage solution)
generated_files = {}
_file_lock = threading.Lock()

# Global variable to store the cleanup thread
cleanup_thread = None
cleanup_thread_running = False

def is_valid_table_name(table_name):
    """Check if a table name is a valid SQLite identifier"""
    if not table_name or not isinstance(table_name, str):
        return False
    
    # Table names should be valid SQLite identifiers
    # They should start with a letter or underscore and contain only letters, digits, and underscores
    if not (table_name[0].isalpha() or table_name[0] == '_'):
        return False
    
    # Check that all characters are alphanumeric or underscore
    for char in table_name:
        if not (char.isalnum() or char == '_'):
            return False
    
    return True

def get_table_names():
    """Get list of all table names in the database"""
    # Get the database path - try different methods
    try:
        db_path = DevConfig.DB_PATH
    except:
        # Fallback to direct path construction
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app.db')
    
    # Connect to the database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all table names in alphabetical order
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = cursor.fetchall()
    
    # Close connection
    conn.close()
    
    # Extract table names from tuples and return in alphabetical order
    table_names = [table[0] for table in tables]
    
    # Validate table names to prevent SQL injection
    for table_name in table_names:
        if not is_valid_table_name(table_name):
            raise ValueError(f"Invalid table name format: {table_name}")
    
    return table_names

def export_table_to_excel(table_name):
    """Export a specific table to Excel format"""
    # Validate table name format
    if not is_valid_table_name(table_name):
        raise ValueError(f"Invalid table name format: {table_name}")
    
    # Get available tables and validate table name
    available_tables = get_table_names()
    if table_name not in available_tables:
        raise ValueError(f"Invalid table name: {table_name}")
    
    # Get the database path - try different methods
    try:
        db_path = DevConfig.DB_PATH
    except:
        # Fallback to direct path construction
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app.db')
    
    # Connect to the database
    conn = sqlite3.connect(db_path)
    
    # Read the table into a pandas DataFrame
    # Use SQLite identifier quoting to prevent SQL injection
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
    except Exception as e:
        conn.close()
        raise e
    
    # Close connection
    conn.close()
    
    # Create a temporary file
    temp_file = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    temp_file.close()
    
    # Save DataFrame to Excel file
    try:
        df.to_excel(temp_file.name, sheet_name=table_name, index=False)
    except Exception as e:
        # Clean up the temporary file if Excel generation fails
        try:
            os.remove(temp_file.name)
        except:
            pass
        raise e
    
    return temp_file.name

def export_multiple_tables_to_excel(table_names):
    """Export multiple tables to a single Excel file with multiple sheets"""
    # Validate all table names format
    for table_name in table_names:
        if not is_valid_table_name(table_name):
            raise ValueError(f"Invalid table name format: {table_name}")
    
    # Get available tables and validate all table names
    available_tables = get_table_names()
    for table_name in table_names:
        if table_name not in available_tables:
            raise ValueError(f"Invalid table name: {table_name}")
    
    # Get the database path - try different methods
    try:
        db_path = DevConfig.DB_PATH
    except:
        # Fallback to direct path construction
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app.db')
    
    # Create a temporary file
    temp_file = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    temp_file.close()
    
    # Create Excel file with multiple sheets
    try:
        with pd.ExcelWriter(temp_file.name, engine='openpyxl') as writer:
            for table_name in table_names:
                # Connect to the database
                conn = sqlite3.connect(db_path)
                
                # Read the table into a pandas DataFrame
                # Use SQLite identifier quoting to prevent SQL injection
                try:
                    df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
                except Exception as e:
                    conn.close()
                    # Clean up the excel file if something fails
                    try:
                        os.remove(temp_file.name)
                    except:
                        pass
                    raise e
                
                # Close connection
                conn.close()
                
                # Write DataFrame to a sheet in the Excel file
                df.to_excel(writer, sheet_name=table_name, index=False)
    except Exception as e:
        # Clean up the temporary file if Excel generation fails
        try:
            os.remove(temp_file.name)
        except:
            pass
        raise e
    
    return temp_file.name

def cleanup_expired_files():
    """Clean up expired export files that haven't been downloaded within the TTL period"""
    try:
        cutoff = datetime.now() - timedelta(hours=1)
        expired = []
        
        # Create a copy of items to avoid dictionary modification during iteration
        with _file_lock:
            for file_id, info in list(generated_files.items()):
                try:
                    created_at = datetime.fromisoformat(info['created_at'])
                    if created_at < cutoff:
                        expired.append((file_id, info))
                except (ValueError, KeyError) as e:
                    # If there's an issue parsing the timestamp, clean up the entry
                    logging.warning(f"Invalid timestamp for file {file_id}, marking for cleanup: {e}")
                    expired.append((file_id, info))
        
        # Clean up expired files
        for file_id, info in expired:
            try:
                if os.path.exists(info['path']):
                    os.remove(info['path'])
                with _file_lock:
                    generated_files.pop(file_id, None)
                logging.info(f"Cleaned up expired file {file_id}")
            except Exception as e:
                logging.error(f"Cleanup failed for {file_id}: {e}")
    except Exception as e:
        logging.error(f"Error during file cleanup: {e}")

def start_cleanup_thread():
    """Start a background thread to periodically clean up expired files"""
    global cleanup_thread, cleanup_thread_running
    
    def cleanup_loop():
        global cleanup_thread_running
        cleanup_thread_running = True
        while cleanup_thread_running:
            try:
                cleanup_expired_files()
                # Sleep for 10 minutes before next cleanup
                threading.Event().wait(600)  # 10 minutes
            except Exception as e:
                logging.error(f"Error in cleanup thread: {e}")
                # Continue running even if an error occurs
    
    # Start the cleanup thread if it's not already running
    if cleanup_thread is None or not cleanup_thread.is_alive():
        cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        cleanup_thread.start()
        logging.info("File cleanup thread started")

def stop_cleanup_thread():
    """Stop the background cleanup thread"""
    global cleanup_thread_running
    cleanup_thread_running = False

@db_export_bp.route('/db/tables', methods=['GET'])
@auth_required()
@roles_required('admin')
def get_tables():
    """
    Get list of all tables in the database with their indices
    Returns:
        JSON: List of table names with indices
    """
    try:
        tables = get_table_names()
        # Create a list with indices
        tables_with_indices = []
        for i, table_name in enumerate(tables):
            tables_with_indices.append({
                'index': i,
                'name': table_name
            })
        
        return jsonify({
            'success': True,
            'tables': tables_with_indices,
            'count': len(tables)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@db_export_bp.route('/db/export', methods=['POST'])
@auth_required()
@roles_required('admin')
def export_table():
    """
    Export one or more tables to Excel format
    Request Body:
        table_name (str): Name of a single table to export
        OR
        table_names (list): List of table names to export
        OR
        table_indices (list): List of table indices to export
    Returns:
        JSON: URL to download the Excel file
    """
    # Initialize excel_file_path to avoid unbound variable issues in exception handler
    # This must be outside the try block to ensure it's accessible in the except block
    excel_file_path = None
    try:
        # Get data from request body
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body is required'
            }), 400
        
        # Get available tables
        available_tables = get_table_names()
        
        # Check if exporting single or multiple tables
        if 'table_name' in data:
            # Single table export by name
            table_name = data['table_name']
            
            # Validate table name format
            if not is_valid_table_name(table_name):
                return jsonify({
                    'success': False,
                    'error': f'Invalid table name format: "{table_name}"'
                }), 400
            
            # Validate table exists
            if table_name not in available_tables:
                return jsonify({
                    'success': False,
                    'error': f'Table "{table_name}" not found in database. Available tables: {", ".join(available_tables)}'
                }), 404
            
            # Export single table to Excel
            excel_file_path = export_table_to_excel(table_name)
            
            # Check if file was created successfully
            if not os.path.exists(excel_file_path):
                return jsonify({
                    'success': False,
                    'error': 'Failed to create Excel file'
                }), 500
            
            # Generate a unique ID for this file
            file_id = str(uuid.uuid4())
            
            # Store file info
            generated_files[file_id] = {
                'path': excel_file_path,
                'table_name': table_name,
                'created_at': datetime.now().isoformat()
            }
            
            # Return URL to download the file
            download_url = url_for('db_export.download_file', file_id=file_id, _external=True)
            
            return jsonify({
                'success': True,
                'download_url': download_url,
                'table_name': table_name,
                'message': f'Excel file for table "{table_name}" generated successfully'
            })
            
        elif 'table_names' in data:
            # Multiple tables export by names
            table_names = data['table_names']
            
            # Validate all table names format
            invalid_format_tables = [name for name in table_names if not is_valid_table_name(name)]
            if invalid_format_tables:
                return jsonify({
                    'success': False,
                    'error': f'Invalid table name formats: {", ".join(invalid_format_tables)}'
                }), 400
            
            # Validate all tables exist
            invalid_tables = [name for name in table_names if name not in available_tables]
            if invalid_tables:
                return jsonify({
                    'success': False,
                    'error': f'Invalid table names: {", ".join(invalid_tables)}. Available tables: {", ".join(available_tables)}'
                }), 404
            
            # Export multiple tables to single Excel file with multiple sheets
            excel_file_path = export_multiple_tables_to_excel(table_names)
            
            # Check if file was created successfully
            if not os.path.exists(excel_file_path):
                return jsonify({
                    'success': False,
                    'error': 'Failed to create Excel file'
                }), 500
            
            # Generate a unique ID for this file
            file_id = str(uuid.uuid4())
            
            # Store file info
            generated_files[file_id] = {
                'path': excel_file_path,
                'table_names': table_names,
                'created_at': datetime.now().isoformat()
            }
            
            # Return URL to download the file
            download_url = url_for('db_export.download_file', file_id=file_id, _external=True)
            
            return jsonify({
                'success': True,
                'download_url': download_url,
                'table_names': table_names,
                'message': f'Excel file with {len(table_names)} sheets generated successfully'
            })
            
        elif 'table_indices' in data:
            # Multiple tables export by indices
            table_indices = data['table_indices']
            
            # Validate all indices are valid
            invalid_indices = [idx for idx in table_indices if idx < 0 or idx >= len(available_tables)]
            if invalid_indices:
                return jsonify({
                    'success': False,
                    'error': f'Invalid table indices: {invalid_indices}. Available indices: 0 to {len(available_tables) - 1}'
                }), 404
            
            # Convert indices to table names
            table_names = [available_tables[idx] for idx in table_indices]
            
            # Additional validation: ensure we have valid table names
            for table_name in table_names:
                if not is_valid_table_name(table_name):
                    return jsonify({
                        'success': False,
                        'error': f'Invalid table name format in database: "{table_name}"'
                    }), 500
            
            # Export multiple tables to single Excel file with multiple sheets
            excel_file_path = export_multiple_tables_to_excel(table_names)
            
            # Check if file was created successfully
            if not os.path.exists(excel_file_path):
                return jsonify({
                    'success': False,
                    'error': 'Failed to create Excel file'
                }), 500
            
            # Generate a unique ID for this file
            file_id = str(uuid.uuid4())
            
            # Store file info
            generated_files[file_id] = {
                'path': excel_file_path,
                'table_names': table_names,
                'table_indices': table_indices,
                'created_at': datetime.now().isoformat()
            }
            
            # Return URL to download the file
            download_url = url_for('db_export.download_file', file_id=file_id, _external=True)
            
            return jsonify({
                'success': True,
                'download_url': download_url,
                'table_names': table_names,
                'table_indices': table_indices,
                'message': f'Excel file with {len(table_names)} sheets generated successfully'
            })
            
        else:
            return jsonify({
                'success': False,
                'error': 'Either "table_name" (string), "table_names" (array), or "table_indices" (array) is required in request body'
            }), 400
        
    except Exception as e:
        # Try to clean up any temporary files that might have been created
        try:
            if 'excel_file_path' in locals() and excel_file_path is not None and os.path.exists(excel_file_path):
                os.remove(excel_file_path)
        except:
            pass
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@db_export_bp.route('/db/download/<file_id>', methods=['GET'])
@auth_required()
def download_file(file_id):
    """
    Download a previously generated Excel file
    Args:
        file_id (str): Unique identifier for the file
    Returns:
        File: Excel file for download
    """
    try:
        # Check if file exists in our store
        with _file_lock:
            if file_id not in generated_files:
                return jsonify({
                    'success': False,
                    'error': 'File not found or already expired'
                }), 404
            
            file_info = generated_files[file_id]
            file_path = file_info['path']
        
        # Verify the file still exists on disk
        if not os.path.exists(file_path):
            # Clean up the entry if file doesn't exist
            with _file_lock:
                generated_files.pop(file_id, None)
            return jsonify({
                'success': False,
                'error': 'File not found on disk'
            }), 404
        
        # Extract table name for the filename
        if 'table_name' in file_info:
            filename = f"{file_info['table_name']}.xlsx"
        elif 'table_names' in file_info:
            filename = f"export_{len(file_info['table_names'])}_tables.xlsx"
        else:
            filename = "export.xlsx"
        
        # Send the file
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )
        
        # Clean up the file after successful download
        def cleanup():
            with _file_lock:
                try:
                    if file_id in generated_files and os.path.exists(file_path):
                        os.remove(file_path)
                        del generated_files[file_id]
                except Exception as e:
                    logging.error(f"Cleanup failed: {e}")
        
        response.call_on_close(cleanup)
        
        return response
        
    except Exception as e:
        logging.error(f"Error downloading file {file_id}: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# Start the cleanup thread when the module is imported
start_cleanup_thread()