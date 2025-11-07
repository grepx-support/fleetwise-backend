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
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

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

    def calculate_file_hash(self, file_path: str) -> str:
        """
        Calculate MD5 hash of file for deduplication.

        Args:
            file_path: Path to file to hash

        Returns:
            MD5 hash as hex string

        Raises:
            PhotoBackupError: If hash calculation fails
        """
        try:
            md5_hash = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except Exception as e:
            logger.error(f"Failed to calculate hash for {file_path}: {e}")
            raise PhotoBackupError(f"Cannot calculate file hash: {str(e)}")

    def check_duplicate_in_storage(self, source_hash: str, backup_dir: Path) -> Optional[str]:
        """
        Check if file with same hash already exists in backup directory.
        Implements idempotency by preventing duplicate uploads.

        Args:
            source_hash: MD5 hash of source file
            backup_dir: Directory to search for duplicates

        Returns:
            Filename of duplicate if found, None otherwise
        """
        if not backup_dir.exists():
            return None

        try:
            for file_path in backup_dir.glob("*.jpg"):
                if self.calculate_file_hash(str(file_path)) == source_hash:
                    logger.info(f"Duplicate found in storage: {file_path.name}")
                    return file_path.name
        except Exception as e:
            logger.warning(f"Error checking for duplicates: {e}")

        return None

    def backup_photo(self, source_file_path: str, filename: str) -> Tuple[bool, str, Optional[str]]:
        """
        Backup a photo to fleetwise-storage with idempotent deduplication.

        Workflow:
        1. Validate source file exists
        2. Calculate source file hash
        3. Generate date-based backup directory
        4. Check for existing duplicate (idempotency)
        5. Copy file to backup directory
        6. Verify backup integrity
        7. Return relative path for database storage

        Args:
            source_file_path: Full path to source photo file
            filename: Original filename (e.g., "123_45_pickup_1730976543.jpg")

        Returns:
            Tuple of (success: bool, relative_path: str, error_message: Optional[str])
            - success: True if backup completed successfully
            - relative_path: Path relative to storage root (e.g., "images/2025/11/07/123_45_pickup_1730976543.jpg")
            - error_message: Error description if success is False
        """
        try:
            # Step 1: Validate source file
            source_path = Path(source_file_path)
            if not source_path.exists():
                error_msg = f"Source file does not exist: {source_file_path}"
                logger.error(error_msg)
                return False, "", error_msg

            # Step 2: Calculate hash of source file for deduplication
            source_hash = self.calculate_file_hash(source_file_path)
            logger.info(f"Source file hash: {source_hash}")

            # Step 3: Generate date-based backup directory
            backup_dir = self.get_date_based_directory()
            self.ensure_backup_directory(backup_dir)

            # Step 4: Check for duplicate in today's backup directory
            duplicate_filename = self.check_duplicate_in_storage(source_hash, backup_dir)
            if duplicate_filename:
                # Duplicate found - idempotent return
                relative_path = f"images/{backup_dir.relative_to(self.storage_root)}/{duplicate_filename}"
                logger.info(f"Photo already backed up (idempotent): {relative_path}")
                return True, relative_path, None

            # Step 5: Copy file to backup directory
            backup_file_path = backup_dir / filename
            try:
                shutil.copy2(source_file_path, str(backup_file_path))
                logger.info(f"Photo copied to backup: {backup_file_path}")
            except Exception as e:
                error_msg = f"Failed to copy file to backup: {str(e)}"
                logger.error(error_msg)
                return False, "", error_msg

            # Step 6: Verify backup integrity (compare hashes)
            backup_hash = self.calculate_file_hash(str(backup_file_path))
            if backup_hash != source_hash:
                # Backup corrupted - cleanup and fail
                try:
                    backup_file_path.unlink()
                except:
                    pass
                error_msg = "Backup verification failed: hash mismatch"
                logger.error(error_msg)
                return False, "", error_msg

            # Step 7: Success - return relative path for database storage
            relative_path = f"images/{backup_dir.relative_to(self.storage_root)}/{filename}"
            logger.info(f"Photo backup successful: {relative_path}")
            return True, relative_path, None

        except PhotoBackupError as e:
            return False, "", str(e)
        except Exception as e:
            error_msg = f"Unexpected error during photo backup: {str(e)}"
            logger.error(error_msg)
            return False, "", error_msg

    def cleanup_temporary_file(self, file_path: str) -> bool:
        """
        Cleanup temporary file after successful backup.

        Args:
            file_path: Path to temporary file to delete

        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            temp_path = Path(file_path)
            if temp_path.exists():
                temp_path.unlink()
                logger.info(f"Cleaned up temporary file: {file_path}")
                return True
        except Exception as e:
            logger.warning(f"Failed to cleanup temporary file {file_path}: {e}")
            return False

        return True
