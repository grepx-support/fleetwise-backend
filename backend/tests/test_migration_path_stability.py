"""
Test suite for migration path resolution stability.

This test ensures that database paths are resolved consistently across different
execution contexts (different working directories, module vs script execution).
"""
import subprocess
import os
import sys
from pathlib import Path
import pytest


class TestMigrationPathStability:
    """Test path resolution consistency across different execution contexts."""

    @staticmethod
    def get_repo_root() -> Path:
        """Get the root of the fleetwise-backend repository."""
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def get_expected_db_path() -> Path:
        """Get the expected database path based on repository structure."""
        repo_root = TestMigrationPathStability.get_repo_root()
        repos_parent = repo_root.parent
        return repos_parent / "fleetwise-storage" / "database" / "fleetwise.db"

    def test_path_from_repo_root(self):
        """Test path resolution when executing from repository root."""
        repo_root = self.get_repo_root()
        expected_path = self.get_expected_db_path()

        # Run path resolution from repo root
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from backend.utils.paths import get_storage_db_path; print(get_storage_db_path())",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(repo_root)},
        )

        assert (
            result.returncode == 0
        ), f"Failed to resolve path from repo root: {result.stderr}"
        resolved_path = Path(result.stdout.strip())
        assert (
            resolved_path == expected_path
        ), f"Path mismatch from repo root: {resolved_path} != {expected_path}"

    def test_path_from_backend_directory(self):
        """Test path resolution when executing from backend directory."""
        repo_root = self.get_repo_root()
        backend_dir = repo_root / "backend"
        expected_path = self.get_expected_db_path()

        # Run path resolution from backend directory
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, '..'); from backend.utils.paths import get_storage_db_path; print(get_storage_db_path())",
            ],
            cwd=backend_dir,
            capture_output=True,
            text=True,
        )

        assert (
            result.returncode == 0
        ), f"Failed to resolve path from backend directory: {result.stderr}"
        resolved_path = Path(result.stdout.strip())
        assert (
            resolved_path == expected_path
        ), f"Path mismatch from backend directory: {resolved_path} != {expected_path}"

    def test_path_from_migrations_directory(self):
        """Test path resolution when executing from migrations directory."""
        repo_root = self.get_repo_root()
        migrations_dir = repo_root / "backend" / "migrations"
        expected_path = self.get_expected_db_path()

        # Run path resolution from migrations directory
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, '../..'); from backend.utils.paths import get_storage_db_path; print(get_storage_db_path())",
            ],
            cwd=migrations_dir,
            capture_output=True,
            text=True,
        )

        assert (
            result.returncode == 0
        ), f"Failed to resolve path from migrations directory: {result.stderr}"
        resolved_path = Path(result.stdout.strip())
        assert (
            resolved_path == expected_path
        ), f"Path mismatch from migrations directory: {resolved_path} != {expected_path}"

    def test_all_execution_contexts_return_same_path(self):
        """Test that all execution contexts return the same database path."""
        repo_root = self.get_repo_root()
        expected_path = self.get_expected_db_path()

        # Test from repo root
        result1 = subprocess.run(
            [
                sys.executable,
                "-c",
                "from backend.utils.paths import get_storage_db_path; print(get_storage_db_path())",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(repo_root)},
        )

        # Test from backend directory
        result2 = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, '..'); from backend.utils.paths import get_storage_db_path; print(get_storage_db_path())",
            ],
            cwd=repo_root / "backend",
            capture_output=True,
            text=True,
        )

        path1 = result1.stdout.strip()
        path2 = result2.stdout.strip()

        assert path1 == path2, f"Inconsistent paths: {path1} != {path2}"
        assert (
            Path(path1) == expected_path
        ), f"Resolved path doesn't match expected: {path1}"

    def test_storage_directory_exists(self):
        """Test that the storage directory structure exists or can be created."""
        expected_path = self.get_expected_db_path()
        storage_dir = expected_path.parent

        # The storage directory should exist or be creatable
        assert (
            storage_dir.parent.exists()
        ), f"Parent of storage directory doesn't exist: {storage_dir.parent}"

    def test_repo_root_detection(self):
        """Test that repository root is correctly detected."""
        from backend.utils.paths import find_repo_root

        repo_root = find_repo_root()
        assert repo_root.exists(), f"Repository root doesn't exist: {repo_root}"
        assert (
            repo_root / ".git"
        ).exists(), f"Repository marker (.git) not found at {repo_root}"

    def test_repo_root_detection_from_different_paths(self):
        """Test that repo root detection works from different starting points."""
        from backend.utils.paths import find_repo_root

        expected_root = self.get_repo_root()

        # Test from backend directory
        backend_dir = expected_root / "backend"
        root_from_backend = find_repo_root(backend_dir)
        assert (
            root_from_backend == expected_root
        ), f"Repo root detection failed from backend: {root_from_backend}"

        # Test from migrations directory
        migrations_dir = expected_root / "backend" / "migrations"
        root_from_migrations = find_repo_root(migrations_dir)
        assert (
            root_from_migrations == expected_root
        ), f"Repo root detection failed from migrations: {root_from_migrations}"

        # Test from tests directory
        tests_dir = expected_root / "backend" / "tests"
        root_from_tests = find_repo_root(tests_dir)
        assert (
            root_from_tests == expected_root
        ), f"Repo root detection failed from tests: {root_from_tests}"


class TestPathValidation:
    """Test path validation and error handling."""

    def test_storage_db_path_returns_absolute_path(self):
        """Test that get_storage_db_path returns an absolute path."""
        from backend.utils.paths import get_storage_db_path

        db_path = get_storage_db_path()
        assert db_path.is_absolute(), f"Database path is not absolute: {db_path}"

    def test_find_repo_root_validates_marker_exists(self):
        """Test that find_repo_root validates the marker exists."""
        from backend.utils.paths import find_repo_root

        # Should work with default .git marker
        repo_root = find_repo_root()
        assert (repo_root / ".git").exists(), ".git marker not found at repo root"

    def test_find_repo_root_raises_on_missing_marker(self):
        """Test that find_repo_root raises RuntimeError when marker not found."""
        from backend.utils.paths import find_repo_root

        # Try to find a non-existent marker from a temporary directory
        temp_start = Path("/tmp") if os.name != "nt" else Path("C:\\Temp")
        if temp_start.exists():
            with pytest.raises(RuntimeError):
                find_repo_root(temp_start, marker="nonexistent_marker_12345")


class TestEnsureStorageDirectoryExists:
    """Test directory creation and validation."""

    def test_ensure_directory_creation(self):
        """Test that ensure_storage_directory_exists creates required directories."""
        from backend.utils.paths import ensure_storage_directory_exists, get_storage_db_path

        # Call the function to ensure directories exist
        ensure_storage_directory_exists()

        # Verify the directory was created
        db_path = get_storage_db_path()
        assert (
            db_path.parent.exists()
        ), f"Storage directory was not created: {db_path.parent}"
