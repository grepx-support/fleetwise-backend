"""
Centralized path resolution utility for database and storage locations.

This module provides a single source of truth for resolving paths across the
application, ensuring consistency regardless of how the code is executed
(module import, script execution, or different working directories).
"""
from pathlib import Path
from typing import Optional


def find_repo_root(start_path: Optional[Path] = None, marker: str = ".git") -> Path:
    """
    Walk up directory tree to find repository root marked by a marker file/directory.

    Args:
        start_path: Starting path for traversal. If None, uses this file's directory.
        marker: Directory/file name to search for (default: .git for git repositories).

    Returns:
        Path: Absolute path to the repository root containing the marker.

    Raises:
        RuntimeError: If repository root not found within 10 parent levels.

    Note:
        This function is resilient to directory structure changes and symlinks.
        It searches for a repository marker rather than using hardcoded parent counts.
    """
    if start_path is None:
        start_path = Path(__file__).resolve()

    current = start_path.resolve()

    # Search up to 10 levels for repository marker
    for _ in range(10):
        if (current / marker).exists():
            return current

        # Stop if we've reached the filesystem root
        if current.parent == current:
            break

        current = current.parent

    raise RuntimeError(
        f"Repository root (containing '{marker}') not found when searching up from {start_path}. "
        f"Verify you're running from within a git repository."
    )


def get_storage_db_path() -> Path:
    """
    Resolve the fleetwise-storage database file path.

    This function resolves the path to the shared database file located in the
    sibling fleetwise-storage directory. It assumes the following directory structure:

        repos/
        ├── fleetwise-backend/      (current repository)
        │   └── backend/
        │       └── database/
        ├── fleetwise-frontend/     (sibling)
        └── fleetwise-storage/      (sibling where database is stored)
            └── database/
                └── fleetwise.db

    Returns:
        Path: Absolute path to the database file.

    Raises:
        RuntimeError: If repository structure is invalid or storage directory doesn't exist.

    Note:
        This function fails fast with clear error messages if the repository
        structure doesn't match expectations, preventing silent configuration errors.
    """
    try:
        # Find the fleetwise-backend repository root
        repo_root = find_repo_root()

        # The repository root should be fleetwise-backend
        # Navigate up one level to reach the repos folder containing sibling directories
        repos_parent = repo_root.parent

        # Construct path to sibling fleetwise-storage/database directory
        storage_path = repos_parent / "fleetwise-storage" / "database"

        # Validate that the storage directory structure exists
        if not storage_path.exists():
            raise RuntimeError(
                f"Storage directory not found at {storage_path}. "
                f"Repository structure should be:\n"
                f"  repos/\n"
                f"  ├── fleetwise-backend/  (current repo)\n"
                f"  └── fleetwise-storage/  (required sibling)\n"
                f"      └── database/\n"
            )

        db_file = storage_path / "fleetwise.db"
        return db_file

    except RuntimeError as e:
        # Re-raise repository root errors with additional context
        raise RuntimeError(
            f"Failed to resolve database path: {e}\n"
            f"Ensure fleetwise-backend is run from its repository root or a subdirectory."
        ) from e


def ensure_storage_directory_exists() -> None:
    """
    Ensure the storage directory exists, creating it if necessary.

    This function creates parent directories for the database file if they don't exist.
    It should be called during application initialization to guarantee the database
    can be written to.

    Raises:
        RuntimeError: If the directory cannot be created (permission issues, etc.).
    """
    try:
        db_path = get_storage_db_path()
        db_dir = db_path.parent

        db_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise RuntimeError(
            f"Failed to create storage directory: {e}\n"
            f"Check that you have write permissions in the repos directory."
        ) from e
