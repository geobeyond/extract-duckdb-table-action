"""Tests for git history mode - comparing a duckdb table with its previous commit version.

This tests the scenario where only a duckdb table is extracted and
compares the current version with the previous git commit version.
"""

import subprocess
from pathlib import Path

import pytest

import sys

sys.path.insert(0, "src")
sys.path.insert(0, "tests")

from conftest import ITALIAN_CITIES_BASE, ITALIAN_CITIES_MODIFIED, create_geopackage
from geodiff import compute_diff
from git_utils import (
    GitError,
    get_file_from_commit,
    get_previous_commit,
    has_file_in_commit,
    is_git_repo,
)


@pytest.fixture
def git_repo_with_gpkg(tmp_path):
    """
    Create a git repository with a GeoPackage file that has been modified across commits.

    Commit 1: Initial GeoPackage with 5 Italian cities (Roma, Milano, Napoli, Torino, Firenze)
    Commit 2: Modified GeoPackage with changes:
        - Roma: updated description and population
        - Milano: unchanged
        - Napoli: deleted
        - Torino: updated description and population
        - Firenze: deleted
        - Bologna: added
        - Venezia: added

    Returns:
        tuple: (repo_path, gpkg_relative_path)
    """
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )

    # Create data directory
    data_dir = repo_dir / "data"
    data_dir.mkdir()

    # Create initial GeoPackage with 5 Italian cities and commit
    gpkg_path = data_dir / "cities.gpkg"
    create_geopackage(
        str(gpkg_path),
        table_name="cities",
        features=ITALIAN_CITIES_BASE,
        description="Italian cities dataset - Initial",
    )

    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit with 5 Italian cities"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )

    # Modify the GeoPackage (update, delete, insert) and commit
    gpkg_path.unlink()  # Remove old file
    create_geopackage(
        str(gpkg_path),
        table_name="cities",
        features=ITALIAN_CITIES_MODIFIED,
        description="Italian cities dataset - Modified",
    )

    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Update cities: add Bologna/Venezia, remove Napoli/Firenze, update Roma/Torino"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )

    return repo_dir, "data/cities.gpkg"


@pytest.fixture
def git_repo_with_new_gpkg(tmp_path):
    """
    Create a git repository where a GeoPackage file is newly added (doesn't exist in previous commit).

    Commit 1: Empty commit (or other files)
    Commit 2: New GeoPackage added

    Returns:
        tuple: (repo_path, gpkg_relative_path)
    """
    repo_dir = tmp_path / "test_repo_new"
    repo_dir.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )

    # Create initial commit with a dummy file
    readme = repo_dir / "README.md"
    readme.write_text("# Test Repository")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )

    # Add GeoPackage in second commit
    data_dir = repo_dir / "data"
    data_dir.mkdir()
    gpkg_path = data_dir / "new_cities.gpkg"
    create_geopackage(
        str(gpkg_path),
        table_name="cities",
        features=ITALIAN_CITIES_BASE,
        description="Italian cities dataset - New file",
    )

    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Add new GeoPackage with Italian cities"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
    )

    return repo_dir, "data/new_cities.gpkg"


class TestGitHistoryModeExtraction:
    """Tests for extracting and comparing files from git history."""

    def test_extract_previous_version(self, git_repo_with_gpkg):
        """Test extracting the previous version of a GeoPackage from git history."""
        repo_path, gpkg_rel_path = git_repo_with_gpkg

        # Get previous commit
        prev_commit = get_previous_commit(str(repo_path))
        assert prev_commit is not None
        assert len(prev_commit) == 40  # Full SHA

        # Verify file exists in previous commit
        assert has_file_in_commit(str(repo_path), gpkg_rel_path, prev_commit) is True

        # Extract file from previous commit
        extracted_path = get_file_from_commit(str(repo_path), gpkg_rel_path, prev_commit)
        assert extracted_path is not None
        assert Path(extracted_path).exists()
        assert extracted_path.endswith(".gpkg")

        # Cleanup
        Path(extracted_path).unlink()

    def test_compare_with_previous_commit(self, git_repo_with_gpkg):
        """Test computing diff between current and previous commit version."""
        repo_path, gpkg_rel_path = git_repo_with_gpkg

        # Get paths
        current_file = repo_path / gpkg_rel_path
        prev_commit = get_previous_commit(str(repo_path))
        prev_file = get_file_from_commit(str(repo_path), gpkg_rel_path, prev_commit)

        try:
            # Compute diff: previous -> current
            result = compute_diff(prev_file, str(current_file))

            # Verify changes detected
            assert result["has_changes"] is True
            assert result["summary"]["total_changes"] == 6

            # Verify exact change counts
            # Changes: 2 inserts (Bologna, Venezia), 2 updates (Roma, Torino), 2 deletes (Napoli, Firenze)
            assert result["summary"]["inserts"] == 2, f"Expected 2 inserts, got {result['summary']['inserts']}"
            assert result["summary"]["updates"] == 2, f"Expected 2 updates, got {result['summary']['updates']}"
            assert result["summary"]["deletes"] == 2, f"Expected 2 deletes, got {result['summary']['deletes']}"

        finally:
            # Cleanup
            Path(prev_file).unlink()

    def test_new_file_not_in_previous_commit(self, git_repo_with_new_gpkg):
        """Test that a newly added file is correctly identified as not existing in previous commit."""
        repo_path, gpkg_rel_path = git_repo_with_new_gpkg

        # Get previous commit
        prev_commit = get_previous_commit(str(repo_path))

        # Verify file does NOT exist in previous commit
        assert has_file_in_commit(str(repo_path), gpkg_rel_path, prev_commit) is False

    def test_extract_nonexistent_file_raises_error(self, git_repo_with_new_gpkg):
        """Test that extracting a file that doesn't exist in previous commit raises error."""
        repo_path, gpkg_rel_path = git_repo_with_new_gpkg

        prev_commit = get_previous_commit(str(repo_path))

        with pytest.raises(GitError, match="File not found in commit"):
            get_file_from_commit(str(repo_path), gpkg_rel_path, prev_commit)


class TestGitHistoryModeChangesets:
    """Tests for verifying changeset details when comparing with git history."""

    def test_changeset_has_cities_table(self, git_repo_with_gpkg):
        """Test that changeset from git history contains the cities table."""
        repo_path, gpkg_rel_path = git_repo_with_gpkg

        current_file = repo_path / gpkg_rel_path
        prev_commit = get_previous_commit(str(repo_path))
        prev_file = get_file_from_commit(str(repo_path), gpkg_rel_path, prev_commit)

        try:
            result = compute_diff(prev_file, str(current_file))

            # Verify cities table is in changeset
            changes = result["changes"]["geodiff"]
            assert len(changes) > 0

            cities_table = None
            for table_change in changes:
                if table_change.get("table") == "cities":
                    cities_table = table_change
                    break

            assert cities_table is not None, "Expected 'cities' table in changeset"

        finally:
            Path(prev_file).unlink()

    def test_changeset_detail_types(self, git_repo_with_gpkg):
        """Test that changeset contains correct change types (insert, update, delete)."""
        repo_path, gpkg_rel_path = git_repo_with_gpkg

        current_file = repo_path / gpkg_rel_path
        prev_commit = get_previous_commit(str(repo_path))
        prev_file = get_file_from_commit(str(repo_path), gpkg_rel_path, prev_commit)

        try:
            result = compute_diff(prev_file, str(current_file))

            # Count change types from changeset
            changes = result["changes"]["geodiff"]
            inserts = 0
            updates = 0
            deletes = 0

            for table_change in changes:
                for change in table_change.get("changes", []):
                    change_type = change.get("type")
                    if change_type == "insert":
                        inserts += 1
                    elif change_type == "update":
                        updates += 1
                    elif change_type == "delete":
                        deletes += 1

            # Verify counts match expected
            assert inserts == 2, f"Expected 2 inserts (Bologna, Venezia), got {inserts}"
            assert updates == 2, f"Expected 2 updates (Roma, Torino), got {updates}"
            assert deletes == 2, f"Expected 2 deletes (Napoli, Firenze), got {deletes}"

        finally:
            Path(prev_file).unlink()


class TestGitHistoryModeEdgeCases:
    """Tests for edge cases in git history mode."""

    def test_identical_commits(self, tmp_path):
        """Test comparing a file that hasn't changed between commits."""
        repo_dir = tmp_path / "identical_repo"
        repo_dir.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )

        # Create GeoPackage and commit
        gpkg_path = repo_dir / "data.gpkg"
        create_geopackage(
            str(gpkg_path),
            table_name="cities",
            features=ITALIAN_CITIES_BASE,
        )

        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )

        # Create another commit without changing the GeoPackage
        readme = repo_dir / "README.md"
        readme.write_text("# Documentation")
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Add README"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )

        # Compare with previous commit - should show no changes
        prev_commit = get_previous_commit(str(repo_dir))
        prev_file = get_file_from_commit(str(repo_dir), "data.gpkg", prev_commit)

        try:
            result = compute_diff(prev_file, str(gpkg_path))

            assert result["has_changes"] is False
            assert result["summary"]["total_changes"] == 0
            assert result["summary"]["inserts"] == 0
            assert result["summary"]["updates"] == 0
            assert result["summary"]["deletes"] == 0

        finally:
            Path(prev_file).unlink()

    def test_single_commit_repo_raises_error(self, tmp_path):
        """Test that a repo with only one commit raises appropriate error."""
        repo_dir = tmp_path / "single_commit_repo"
        repo_dir.mkdir()

        # Initialize git repo with single commit
        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )

        gpkg_path = repo_dir / "data.gpkg"
        create_geopackage(str(gpkg_path), table_name="cities", features=ITALIAN_CITIES_BASE)

        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Only commit"],
            cwd=repo_dir,
            capture_output=True,
            check=True,
        )

        # Trying to get previous commit should fail
        with pytest.raises(GitError, match="No previous commit"):
            get_previous_commit(str(repo_dir), offset=1)

    def test_non_git_directory_raises_error(self, tmp_path):
        """Test that a non-git directory raises appropriate error."""
        non_git_dir = tmp_path / "not_a_repo"
        non_git_dir.mkdir()

        assert is_git_repo(str(non_git_dir)) is False

        with pytest.raises(GitError, match="Not a git repository"):
            get_previous_commit(str(non_git_dir))


class TestGitHistoryModeIntegration:
    """Integration tests simulating the full git history mode workflow."""

    def test_full_workflow_with_changes(self, git_repo_with_gpkg):
        """Test the complete workflow: detect repo, extract previous, compute diff."""
        repo_path, gpkg_rel_path = git_repo_with_gpkg

        # Step 1: Verify it's a git repo
        assert is_git_repo(str(repo_path)) is True

        # Step 2: Get previous commit
        prev_commit = get_previous_commit(str(repo_path))
        assert prev_commit is not None

        # Step 3: Check file exists in previous commit
        assert has_file_in_commit(str(repo_path), gpkg_rel_path, prev_commit) is True

        # Step 4: Extract previous version
        prev_file = get_file_from_commit(str(repo_path), gpkg_rel_path, prev_commit)
        assert Path(prev_file).exists()

        try:
            # Step 5: Compute diff
            current_file = str(repo_path / gpkg_rel_path)
            result = compute_diff(prev_file, current_file)

            # Step 6: Verify results
            assert result["has_changes"] is True
            assert result["summary"]["total_changes"] == 6
            assert result["summary"]["inserts"] == 2
            assert result["summary"]["updates"] == 2
            assert result["summary"]["deletes"] == 2

            # Verify changeset details
            changes = result["changes"]["geodiff"]
            assert len(changes) > 0
            assert any(t.get("table") == "cities" for t in changes)

        finally:
            Path(prev_file).unlink()

    def test_full_workflow_new_file(self, git_repo_with_new_gpkg):
        """Test the workflow when the file is new (doesn't exist in previous commit)."""
        repo_path, gpkg_rel_path = git_repo_with_new_gpkg

        # Verify it's a git repo
        assert is_git_repo(str(repo_path)) is True

        # Get previous commit
        prev_commit = get_previous_commit(str(repo_path))

        # File should NOT exist in previous commit
        assert has_file_in_commit(str(repo_path), gpkg_rel_path, prev_commit) is False

        # In this case, the action would report this as a "new file"
        # and not attempt to extract from previous commit
