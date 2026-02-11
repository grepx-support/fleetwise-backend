"""
Photo Backup Service

Handles automatic backup of job-related photos to fleetwise-storage repository.
- Organizes photos by date (YYYY/MM/DD)
- Ensures idempotency (no duplicate files on retry)
- Updates database paths after successful backup
- Manages cleanup of temporary files
"""

import os
import shutil
import hashlib
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

# File size limits (in bytes)
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB
CHUNK_SIZE = 64 * 1024  # 64KB chunks for streaming

logger = logging.getLogger(__name__)


class PhotoBackupError(Exception):
    """Custom exception for photo backup errors"""
    pass


class PhotoBackupService:
    """
    Service to backup job photos to fleetwise-storage repository.

    Features:
    - Organizes photos by date in YYYY/MM/DD directory structure
    - Idempotent: checks for duplicate files using hash comparison
    - Atomic operations: verify backup before deleting temporary file
    - Database integration: tracks relative paths in JobPhoto.file_path
    """

    def __init__(self, storage_root: str):
        """
        Initialize PhotoBackupService.

        Args:
            storage_root: Base path to fleetwise-storage (e.g., ../fleetwise-storage/images)
        """
        self.storage_root = Path(storage_root)
        self.ensure_storage_root_exists()

    def ensure_storage_root_exists(self):
        """Ensure storage root directory exists"""
        try:
            self.storage_root.mkdir(parents=True, exist_ok=True)
            logger.info(f"Photo storage root initialized: {self.storage_root}")
        except Exception as e:
            logger.error(f"Failed to create storage root: {e}")
            raise PhotoBackupError(f"Cannot create storage directory: {str(e)}")

    def get_date_based_directory(self) -> Path:
        """
        Generate date-based directory path (YYYY/MM/DD).

        Returns:
            Path object for the dated directory
        """
        now = datetime.now()
        date_path = self.storage_root / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        return date_path

    def ensure_backup_directory(self, backup_path: Path) -> None:
        """
        Ensure backup directory exists.

        Args:
            backup_path: Path to ensure exists

        Raises:
            PhotoBackupError: If directory creation fails
        """
        try:
            backup_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create backup directory {backup_path}: {e}")
            raise PhotoBackupError(f"Cannot create backup directory: {str(e)}")

    def validate_file_size(self, file_path: str) -> bool:
        """
        Validate that file size is within acceptable limits.

        Args:
            file_path: Path to file to validate

        Returns:
            True if file size is acceptable, False otherwise
        """
        try:
            file_size = os.path.getsize(file_path)
            if file_size > MAX_PHOTO_SIZE:
                logger.error(f"File too large: {file_path} ({file_size} bytes > {MAX_PHOTO_SIZE} bytes)")
                return False
            if file_size == 0:
                logger.error(f"File is empty: {file_path}")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to validate file size for {file_path}: {e}")
            return False
    
    def calculate_file_hash(self, file_path: str) -> str:
        """
        Calculate MD5 hash of file for deduplication with streaming.

        Args:
            file_path: Path to file to hash

        Returns:
            MD5 hash as hex string

        Raises:
            PhotoBackupError: If hash calculation fails
        """
        try:
            md5_hash = hashlib.md5()
            file_size = os.path.getsize(file_path)
            bytes_processed = 0
            start_time = time.time()
            
            with open(file_path, 'rb') as f:
                while chunk := f.read(CHUNK_SIZE):
                    md5_hash.update(chunk)
                    bytes_processed += len(chunk)
                    
                    # Log progress for large files
                    if file_size > 5 * 1024 * 1024:  # > 5MB
                        progress = (bytes_processed / file_size) * 100
                        if progress % 20 < (CHUNK_SIZE / file_size) * 100:  # Log every ~20%
                            logger.debug(f"Hashing progress: {progress:.1f}% ({bytes_processed}/{file_size} bytes)")
            
            duration = time.time() - start_time
            logger.debug(f"File hashing completed in {duration:.2f}s ({file_size} bytes)")
            return md5_hash.hexdigest()
        except Exception as e:
            logger.error(f"Failed to calculate hash for {file_path}: {e}")
            raise PhotoBackupError(f"Cannot calculate file hash: {str(e)}")

    def generate_idempotent_filename(self, source_hash: str, original_filename: str) -> str:
        """
        Generate idempotent filename using hash prefix.

        Uses first 16 characters of MD5 hash to ensure same file content
        always gets same filename (idempotency), avoiding expensive
        directory scans on each upload.

        Args:
            source_hash: MD5 hash of source file (32 chars)
            original_filename: Original filename for extension

        Returns:
            Filename with format: {hash_prefix}{extension}
            Example: "a38e8cb199cbad04.jpg"
        """
        ext = Path(original_filename).suffix.lower()
        if ext not in ['.jpg', '.jpeg', '.png']:
            ext = '.jpg'  # Default to jpg if unknown

        # Use 16-char hash prefix (128 bits = sufficient for collision resistance)
        hash_prefix = source_hash[:16]
        return f"{hash_prefix}{ext}"

    def check_hash_filename_exists(self, hash_filename: str, backup_dir: Path) -> bool:
        """
        O(1) check if file with hash-based filename already exists.

        Much faster than scanning/hashing entire directory.

        Args:
            hash_filename: Filename generated by generate_idempotent_filename()
            backup_dir: Directory to check

        Returns:
            True if file exists, False otherwise
        """
        if not backup_dir.exists():
            return False

        file_path = backup_dir / hash_filename
        return file_path.exists()

    def backup_photo(self, source_file_path: str, filename: str) -> Tuple[bool, str, Optional[str]]:
        """
        Backup a photo to fleetwise-storage with O(1) idempotent deduplication.

        Workflow:
        1. Validate source file exists
        2. Calculate source file hash
        3. Generate hash-based idempotent filename
        4. Generate date-based backup directory
        5. O(1) check if file already exists (idempotency)
        6. Copy file to backup directory if new
        7. Verify backup integrity
        8. Return relative path for database storage

        Performance: O(1) per upload (no directory scanning)
        Idempotency: Same content always gets same filename

        Args:
            source_file_path: Full path to source photo file
            filename: Original filename for extension extraction

        Returns:
            Tuple of (success: bool, relative_path: str, error_message: Optional[str])
            - success: True if backup completed successfully
            - relative_path: Path relative to storage root (e.g., "images/2025/11/07/a38e8cb199cbad04.jpg")
            - error_message: Error description if success is False
        """
        temp_file_path = None
        try:
            # Step 1: Validate source file existence and size
            source_path = Path(source_file_path)
            if not source_path.exists():
                error_msg = f"Source file does not exist: {source_file_path}"
                logger.error(error_msg)
                return False, "", error_msg
                
            # Validate file size
            if not self.validate_file_size(source_file_path):
                error_msg = f"Source file size validation failed: {source_file_path}"
                logger.error(error_msg)
                return False, "", error_msg

            # Step 2: Calculate hash of source file for idempotent naming
            source_hash = self.calculate_file_hash(source_file_path)
            logger.info(f"Source file hash: {source_hash}")

            # Step 3: Generate idempotent filename using hash prefix
            # This ensures same content always maps to same filename
            hash_filename = self.generate_idempotent_filename(source_hash, filename)
            logger.info(f"Idempotent filename: {hash_filename}")

            # Step 4: Generate date-based backup directory
            backup_dir = self.get_date_based_directory()
            self.ensure_backup_directory(backup_dir)

            # Step 5: O(1) check if file already exists (idempotency)
            # No directory scanning - just check if file path exists
            backup_file_path = backup_dir / hash_filename
            if backup_file_path.exists():
                relative_path = f"images/{backup_dir.relative_to(self.storage_root)}/{hash_filename}"
                logger.info(f"Photo already backed up (idempotent): {relative_path}")
                return True, relative_path, None

            # Step 6: Copy file to backup directory with streaming
            try:
                start_time = time.time()
                file_size = os.path.getsize(source_file_path)
                bytes_copied = 0
                
                with open(source_file_path, 'rb') as src, open(backup_file_path, 'wb') as dst:
                    while chunk := src.read(CHUNK_SIZE):
                        dst.write(chunk)
                        bytes_copied += len(chunk)
                        
                        # Log progress for large files
                        if file_size > 5 * 1024 * 1024:  # > 5MB
                            progress = (bytes_copied / file_size) * 100
                            if progress % 20 < (CHUNK_SIZE / file_size) * 100:  # Log every ~20%
                                logger.debug(f"Copy progress: {progress:.1f}% ({bytes_copied}/{file_size} bytes)")
                
                # Preserve metadata
                shutil.copystat(source_file_path, str(backup_file_path))
                
                duration = time.time() - start_time
                logger.info(f"Photo copied to backup: {backup_file_path} ({duration:.2f}s, {file_size} bytes)")
                
            except Exception as e:
                error_msg = f"Failed to copy file to backup: {str(e)}"
                logger.error(error_msg)
                # Attempt cleanup of partial file
                try:
                    if backup_file_path.exists():
                        backup_file_path.unlink()
                        logger.info(f"Cleaned up partial backup file: {backup_file_path}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to cleanup partial backup: {cleanup_error}")
                return False, "", error_msg

            # Step 7: Verify backup integrity (compare hashes)
            # Critical check to ensure no corruption during copy
            backup_hash = self.calculate_file_hash(str(backup_file_path))
            if backup_hash != source_hash:
                # Backup corrupted - cleanup and fail
                try:
                    backup_file_path.unlink()
                    logger.warning(f"Cleaned up corrupted backup: {backup_file_path}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to cleanup corrupted backup: {cleanup_error}")

                error_msg = "Backup verification failed: hash mismatch"
                logger.error(error_msg)
                return False, "", error_msg

            # Step 8: Success - return relative path for database storage
            relative_path = f"images/{backup_dir.relative_to(self.storage_root)}/{hash_filename}"
            logger.info(f"Photo backup successful: {relative_path}")
            return True, relative_path, None

        except PhotoBackupError as e:
            logger.error(f"Backup error: {str(e)}")
            return False, "", str(e)
        except Exception as e:
            error_msg = f"Unexpected error during photo backup: {str(e)}"
            logger.error(error_msg, exc_info=True)
            # Attempt cleanup on unexpected errors
            try:
                if 'backup_file_path' in locals() and backup_file_path.exists():
                    backup_file_path.unlink()
                    logger.info(f"Cleaned up backup file after error: {backup_file_path}")
            except Exception as cleanup_error:
                logger.error(f"Failed to cleanup after error: {cleanup_error}")
            return False, "", error_msg

    def cleanup_temporary_file(self, file_path: str) -> bool:
        """
        Cleanup temporary file after successful backup with enhanced error handling.

        Args:
            file_path: Path to temporary file to delete

        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            temp_path = Path(file_path)
            if temp_path.exists():
                # Check if file is writable before attempting deletion
                if not os.access(file_path, os.W_OK):
                    logger.warning(f"Cannot delete readonly file: {file_path}")
                    return False
                    
                # Get file size for logging
                file_size = temp_path.stat().st_size
                temp_path.unlink()
                logger.info(f"Cleaned up temporary file: {file_path} ({file_size} bytes)")
                return True
            else:
                logger.debug(f"Temporary file not found (already deleted): {file_path}")
                return True
        except PermissionError as e:
            logger.warning(f"Permission denied when deleting temporary file {file_path}: {e}")
            return False
        except OSError as e:
            logger.warning(f"OS error when deleting temporary file {file_path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during temporary file cleanup {file_path}: {e}", exc_info=True)
            return False
