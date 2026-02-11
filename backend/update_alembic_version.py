import sqlite3

# Connect to the database
conn = sqlite3.connect(r'D:\GrepX\wise\orchestrator\repos\fleetwise-storage\database\fleetwise.db')
cursor = conn.cursor()

try:
    # Update the alembic version to the correct one
    cursor.execute("UPDATE alembic_version SET version_num = '2ab53ed947ca'")
    conn.commit()
    print('Alembic version updated to 2ab53ed947ca')
    
    # Verify the update
    cursor.execute("SELECT * FROM alembic_version")
    result = cursor.fetchall()
    print(f'Current alembic version(s): {result}')
    
except sqlite3.Error as e:
    print(f'Database error: {e}')
except Exception as e:
    print(f'Error: {e}')
finally:
    conn.close()