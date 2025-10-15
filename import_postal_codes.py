#!/usr/bin/env python3
"""
Standalone script to import Singapore postal codes from CSV file.
This script can be run independently to populate the postal_codes table.

Usage:
    python import_postal_codes.py
"""

import os
import sys
import csv
from datetime import datetime

# Add the parent directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

try:
    from backend.server import app, db
    from backend.models.postal_code import PostalCode
except ImportError as e:
    print(f"ERROR: Could not import backend modules: {e}")
    print("Make sure you're running this from the correct directory and that backend modules exist.")
    sys.exit(1)


def import_postal_codes(csv_file_path=None, clear_existing=True):
    """
    Import postal codes from CSV file into database
    
    Args:
        csv_file_path (str, optional): Path to CSV file. If None, uses default location.
        clear_existing (bool): Whether to clear existing postal codes before importing.
    
    Returns:
        int: Number of postal codes imported
    """
    
    # Default CSV path
    if csv_file_path is None:
        csv_file_path = os.path.join(current_dir, 'sg_zipcode_mapper.csv')
    
    if not os.path.exists(csv_file_path):
        print(f"ERROR: CSV file not found at {csv_file_path}")
        return 0
    
    print(f"Importing postal codes from: {csv_file_path}")
    
    with app.app_context():
        # Clear existing postal codes if requested
        if clear_existing:
            try:
                existing_count = PostalCode.query.count()
                db.session.query(PostalCode).delete()
                db.session.commit()
                print(f"Cleared {existing_count} existing postal codes")
            except Exception as e:
                print(f"Warning: Could not clear existing postal codes: {e}")
                db.session.rollback()
        
        postal_codes_added = 0
        batch_size = 1000  # Process in batches for better performance
        postal_codes_batch = []
        skipped_rows = 0
        
        try:
            # Try different encodings
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for encoding in encodings:
                try:
                    print(f"Attempting to read file with {encoding} encoding...")
                    
                    # Reset variables for each encoding attempt if previous failed
                    postal_codes_added = 0
                    postal_codes_batch = []
                    skipped_rows = 0
                    
                    with open(csv_file_path, 'r', encoding=encoding) as file:
                        csv_reader = csv.reader(file)
                        
                        print(f"Successfully opened file with {encoding} encoding")
                        print("Processing CSV rows...")
                        
                        seen_postal_codes = set()  # Track duplicates within the file
                        row_count = 0
                        
                        for row_num, row in enumerate(csv_reader, 1):
                            row_count += 1
                            try:
                                # Skip rows that don't have enough columns
                                if len(row) < 9:
                                    skipped_rows += 1
                                    continue
                                
                                # Extract postal code and address from CSV
                                # CSV structure: postal,latitude,longitude,searchval,blk_no,road_name,building,address,postal
                                postal_code = row[0].strip()  # First column
                                address = row[7].strip()      # Address column (8th column, index 7)
                                
                                # Skip if postal code or address is empty
                                if not postal_code or not address:
                                    skipped_rows += 1
                                    continue
                                
                                # Validate postal code (Singapore postal codes are 6 digits)
                                if not postal_code.isdigit() or len(postal_code) != 6:
                                    skipped_rows += 1
                                    continue
                                
                                # Skip duplicates within the file (keep first occurrence)
                                if postal_code in seen_postal_codes:
                                    skipped_rows += 1
                                    continue
                                
                                seen_postal_codes.add(postal_code)
                                
                                # Create PostalCode object
                                postal_code_obj = PostalCode(
                                    postal_code=postal_code,
                                    address=address
                                )
                                
                                postal_codes_batch.append(postal_code_obj)
                                
                                # Process batch when it reaches batch_size
                                if len(postal_codes_batch) >= batch_size:
                                    db.session.bulk_save_objects(postal_codes_batch)
                                    db.session.commit()
                                    postal_codes_added += len(postal_codes_batch)
                                    print(f"Processed {postal_codes_added} unique postal codes... (Row {row_num})")
                                    postal_codes_batch = []
                                    
                            except Exception as e:
                                print(f"Error processing row {row_num}: {e}")
                                skipped_rows += 1
                                continue
                        
                        # Process remaining batch
                        if postal_codes_batch:
                            db.session.bulk_save_objects(postal_codes_batch)
                            db.session.commit()
                            postal_codes_added += len(postal_codes_batch)
                        
                        print(f"\n--- Import Summary ---")
                        print(f"Total postal codes imported: {postal_codes_added}")
                        print(f"Rows skipped: {skipped_rows}")
                        print(f"Total rows processed: {row_count}")
                        print(f"Unique postal codes found: {len(seen_postal_codes)}")
                        
                        # Verify final count
                        final_count = PostalCode.query.count()
                        print(f"Total postal codes in database: {final_count}")
                        
                        return postal_codes_added
                        
                except UnicodeDecodeError as e:
                    print(f"Failed to read with {encoding} encoding: {e}")
                    print("Trying next encoding...")
                    # Clear any partially imported data if the encoding failed
                    if postal_codes_added > 0:
                        print(f"Rolling back {postal_codes_added} partially imported records...")
                        db.session.rollback()
                    continue
                except Exception as e:
                    print(f"Error with {encoding}: {e}")
                    # Clear any partially imported data if there was an error
                    if postal_codes_added > 0:
                        print(f"Rolling back {postal_codes_added} partially imported records...")
                        db.session.rollback()
                    continue
            
            # If we get here, no encoding worked
            print("ERROR: Could not read the file with any encoding")
            return 0
            
        except Exception as e:
            print(f"ERROR: Failed to import postal codes: {e}")
            db.session.rollback()
            return 0


def main():
    """Main function for standalone execution"""
    print("=== Singapore Postal Codes Import ===")
    print(f"Starting import at {datetime.now()}")
    
    # Check if CSV file exists
    csv_path = os.path.join(current_dir, 'sg_zipcode_mapper.csv')
    if not os.path.exists(csv_path):
        print(f"\nERROR: CSV file not found!")
        print(f"Expected location: {csv_path}")
        print("Please ensure the sg_zipcode_mapper.csv file is in the backend directory.")
        return 1
    
    try:
        count = import_postal_codes()
        if count > 0:
            print(f"\n✅ SUCCESS: Imported {count} postal codes successfully!")
            return 0
        else:
            print(f"\n❌ FAILED: No postal codes were imported.")
            return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)