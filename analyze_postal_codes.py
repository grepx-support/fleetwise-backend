#!/usr/bin/env python3
"""
Analyze the Singapore postal codes CSV file to understand the data structure and quality.
"""

import csv
import os
from collections import defaultdict, Counter

def analyze_csv():
    csv_path = 'sg_zipcode_mapper.csv'
    
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV file not found at {csv_path}")
        return
    
    print("=== Singapore Postal Codes CSV Analysis ===\n")
    
    total_rows = 0
    valid_postal_codes = 0
    invalid_postal_codes = 0
    empty_addresses = 0
    duplicates = defaultdict(int)
    postal_code_lengths = Counter()
    
    # Try different encodings
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    file_opened = False
    
    for encoding in encodings:
        try:
            with open(csv_path, 'r', encoding=encoding) as file:
                csv_reader = csv.reader(file)
                
                # Skip header
                header = next(csv_reader, None)
                print(f"Encoding used: {encoding}")
                print(f"Header: {header}")
                print(f"Total columns: {len(header) if header else 0}\n")
                
                for row_num, row in enumerate(csv_reader, 2):  # Start from row 2 (after header)
                    total_rows += 1
                    
                    if len(row) < 9:
                        if total_rows <= 5:
                            print(f"Warning: Row {row_num} has insufficient columns: {len(row)}")
                        continue
                    
                    postal_code = row[0].strip()
                    address = row[7].strip()
                    
                    # Track postal code length distribution
                    postal_code_lengths[len(postal_code)] += 1
                    
                    # Check for duplicates
                    duplicates[postal_code] += 1
                    
                    # Validate postal code
                    if postal_code.isdigit() and len(postal_code) == 6:
                        valid_postal_codes += 1
                    else:
                        invalid_postal_codes += 1
                        if invalid_postal_codes <= 10:  # Show first few invalid ones
                            print(f"Invalid postal code at row {row_num}: '{postal_code}'")
                    
                    # Check for empty addresses
                    if not address:
                        empty_addresses += 1
                
                file_opened = True
                break
                
        except UnicodeDecodeError:
            print(f"Failed to read with {encoding} encoding, trying next...")
            continue
        except Exception as e:
            print(f"Error with {encoding}: {e}")
            continue
    
    if not file_opened:
        print("ERROR: Could not read the file with any encoding")
        return
    
    # Find duplicates
    duplicate_postal_codes = {pc: count for pc, count in duplicates.items() if count > 1}
    
    print("=== Analysis Results ===")
    print(f"Total rows processed: {total_rows}")
    print(f"Valid postal codes (6 digits): {valid_postal_codes}")
    print(f"Invalid postal codes: {invalid_postal_codes}")
    print(f"Empty addresses: {empty_addresses}")
    print(f"Duplicate postal codes: {len(duplicate_postal_codes)}")
    print(f"Unique postal codes: {len(duplicates)}")
    
    print(f"\nPostal code length distribution:")
    for length, count in sorted(postal_code_lengths.items()):
        print(f"  {length} digits: {count} postal codes")
    
    if duplicate_postal_codes:
        print(f"\nFirst 10 duplicate postal codes:")
        for i, (pc, count) in enumerate(list(duplicate_postal_codes.items())[:10]):
            print(f"  {pc}: appears {count} times")
    
    print(f"\nExpected unique postal codes to import: {valid_postal_codes - len(duplicate_postal_codes)}")
    
    # Show sample data
    print(f"\nSample valid records:")
    try:
        with open(csv_path, 'r', encoding=encoding) as file:
            csv_reader = csv.reader(file)
            next(csv_reader)  # Skip header
            
            count = 0
            for row in csv_reader:
                if len(row) >= 9:
                    postal_code = row[0].strip()
                    address = row[7].strip()
                    
                    if postal_code.isdigit() and len(postal_code) == 6 and address:
                        print(f"  {postal_code}: {address[:80]}...")
                        count += 1
                        if count >= 5:
                            break
    except Exception as e:
        print(f"Error reading sample data: {e}")

if __name__ == '__main__':
    analyze_csv()