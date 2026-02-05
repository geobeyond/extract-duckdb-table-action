"""Tests for src/main.py refactored functions."""

import os
import shutil
import sqlite3
import subprocess
import tempfile
import duckdb
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "src")

from main import (
    ActionResult,
    ExtractionConfig,
    ExtractionResult,
    PrintLogger,
    apply_primary_key,
    build_output_paths,
    extract_table_from_duckdb,
    get_output_extension,
    run_extraction,
    sanitize_table_name,
    set_action_outputs,
    table_exists_in_duckdb,
)


class TestExtractionConfig:
    """Tests for ExtractionConfig dataclass."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        config = ExtractionConfig(duckdb_file="test.duckdb", table_name="my_table")
        assert config.output_format == "GPKG"
        assert config.fid_column == "PROGRESSIVO_ACCESSO"
        assert config.primary_key_columns == ["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"]

    def test_output_format_normalized_to_uppercase(self):
        """Test that output format is normalized to uppercase."""
        config = ExtractionConfig(duckdb_file="test.duckdb", table_name="my_table", output_format="gpkg")
        assert config.output_format == "GPKG"

        config = ExtractionConfig(duckdb_file="test.duckdb", table_name="my_table", output_format="parquet")
        assert config.output_format == "PARQUET"

    def test_invalid_output_format_raises_error(self):
        """Test that invalid output format raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported output format"):
            ExtractionConfig(duckdb_file="test.duckdb", table_name="my_table", output_format="CSV")

    def test_custom_primary_key_columns(self):
        """Test that custom primary key columns can be set."""
        config = ExtractionConfig(
            duckdb_file="test.duckdb",
            table_name="my_table",
            primary_key_columns=["col1", "col2", "col3"],
        )
        assert config.primary_key_columns == ["col1", "col2", "col3"]

    def test_custom_fid_column(self):
        """Test that custom FID column can be set."""
        config = ExtractionConfig(
            duckdb_file="test.duckdb",
            table_name="my_table",
            fid_column="custom_fid",
        )
        assert config.fid_column == "custom_fid"


class TestSanitizeTableName:
    """Tests for sanitize_table_name function."""

    def test_alphanumeric_unchanged(self):
        """Test that alphanumeric names are unchanged."""
        assert sanitize_table_name("my_table") == "my_table"
        assert sanitize_table_name("Table123") == "Table123"

    def test_special_chars_replaced(self):
        """Test that special characters are replaced with underscores."""
        assert sanitize_table_name("my-table") == "my_table"
        assert sanitize_table_name("my.table") == "my_table"
        assert sanitize_table_name("my table") == "my_table"

    def test_multiple_special_chars(self):
        """Test handling of multiple consecutive special characters."""
        assert sanitize_table_name("a--b..c") == "a__b__c"


class TestGetOutputExtension:
    """Tests for get_output_extension function."""

    def test_gpkg_extension(self):
        """Test GPKG format returns .gpkg extension."""
        assert get_output_extension("GPKG") == ".gpkg"
        assert get_output_extension("gpkg") == ".gpkg"

    def test_parquet_extension(self):
        """Test PARQUET format returns .parquet extension."""
        assert get_output_extension("PARQUET") == ".parquet"
        assert get_output_extension("parquet") == ".parquet"


class TestBuildOutputPaths:
    """Tests for build_output_paths function."""

    def test_gpkg_paths(self):
        """Test path building for GPKG format."""
        duckdb_path = Path("/data/mydb.duckdb")
        current, previous, tablebased = build_output_paths(duckdb_path, "addresses", "GPKG")

        assert current == Path("/data/mydb-addresses-current.gpkg")
        assert previous == Path("/data/mydb-addresses-previous.gpkg")
        assert tablebased == "addresses.gpkg"

    def test_parquet_paths(self):
        """Test path building for PARQUET format."""
        duckdb_path = Path("/data/mydb.duckdb")
        current, previous, tablebased = build_output_paths(duckdb_path, "addresses", "PARQUET")

        assert current == Path("/data/mydb-addresses-current.parquet")
        assert previous == Path("/data/mydb-addresses-previous.parquet")
        assert tablebased == "addresses.parquet"

    def test_special_chars_in_table_name(self):
        """Test that special characters in table name are sanitized."""
        duckdb_path = Path("/data/mydb.duckdb")
        current, previous, tablebased = build_output_paths(duckdb_path, "my-special.table", "GPKG")

        assert current == Path("/data/mydb-my_special_table-current.gpkg")
        assert previous == Path("/data/mydb-my_special_table-previous.gpkg")
        assert tablebased == "my_special_table.gpkg"


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_success_result(self):
        """Test creating a successful result."""
        result = ExtractionResult(success=True, output_path=Path("/data/output.gpkg"))
        assert result.success is True
        assert result.output_path == Path("/data/output.gpkg")
        assert result.error is None

    def test_failure_result(self):
        """Test creating a failure result."""
        result = ExtractionResult(success=False, error="Table not found")
        assert result.success is False
        assert result.output_path is None
        assert result.error == "Table not found"


class TestActionResult:
    """Tests for ActionResult dataclass."""

    def test_success_with_both_files(self):
        """Test successful result with both current and previous files."""
        result = ActionResult(
            success=True,
            current_file=Path("/data/current.gpkg"),
            previous_file=Path("/data/previous.gpkg"),
            is_first_commit=False,
        )
        assert result.success is True
        assert result.current_file == Path("/data/current.gpkg")
        assert result.previous_file == Path("/data/previous.gpkg")
        assert result.is_first_commit is False

    def test_first_commit_result(self):
        """Test result when it's the first commit (no previous file)."""
        result = ActionResult(
            success=True,
            current_file=Path("/data/current.gpkg"),
            is_first_commit=True,
        )
        assert result.success is True
        assert result.previous_file is None
        assert result.is_first_commit is True


class TestPrintLogger:
    """Tests for PrintLogger class."""

    def test_info_output(self, capsys):
        """Test info method prints correctly."""
        logger = PrintLogger()
        logger.info("Test message")
        captured = capsys.readouterr()
        assert "[INFO] Test message" in captured.out

    def test_debug_output(self, capsys):
        """Test debug method prints correctly."""
        logger = PrintLogger()
        logger.debug("Debug message")
        captured = capsys.readouterr()
        assert "[DEBUG] Debug message" in captured.out

    def test_error_output(self, capsys):
        """Test error method prints correctly."""
        logger = PrintLogger()
        logger.error("Error message")
        captured = capsys.readouterr()
        assert "[ERROR] Error message" in captured.out

    def test_set_failed_output(self, capsys):
        """Test set_failed method prints correctly."""
        logger = PrintLogger()
        logger.set_failed("Failed message")
        captured = capsys.readouterr()
        assert "[FAILED] Failed message" in captured.out

    def test_set_output_output(self, capsys):
        """Test set_output method prints correctly."""
        logger = PrintLogger()
        logger.set_output("key", "value")
        captured = capsys.readouterr()
        assert "[OUTPUT] key=value" in captured.out


class TestSetActionOutputs:
    """Tests for set_action_outputs function."""

    def test_with_both_files(self, tmp_path):
        """Test setting outputs when both files exist."""
        current = tmp_path / "current.gpkg"
        previous = tmp_path / "previous.gpkg"
        current.touch()
        previous.touch()

        result = ActionResult(
            success=True,
            current_file=current,
            previous_file=previous,
        )

        logger = MagicMock()
        set_action_outputs(result, logger)

        logger.set_output.assert_any_call("current_file", str(current))
        logger.set_output.assert_any_call("previous_file", str(previous))

    def test_first_commit(self, tmp_path):
        """Test setting outputs for first commit (no previous file)."""
        current = tmp_path / "current.gpkg"
        current.touch()

        result = ActionResult(
            success=True,
            current_file=current,
            previous_file=None,
            is_first_commit=True,
        )

        logger = MagicMock()
        set_action_outputs(result, logger)

        logger.set_output.assert_any_call("current_file", str(current))
        logger.set_output.assert_any_call("previous_file", "first_commit")


class TestRunExtractionValidation:
    """Tests for run_extraction input validation."""

    def test_nonexistent_duckdb_file(self, tmp_path):
        """Test that nonexistent DuckDB file returns failure."""
        config = ExtractionConfig(
            duckdb_file=str(tmp_path / "nonexistent.duckdb"),
            table_name="test_table",
        )

        logger = MagicMock()
        result = run_extraction(config, logger)

        assert result.success is False
        assert "does not exist" in result.error
        logger.set_failed.assert_called_once()


# --- Integration Tests (inspired by .github/workflows/test.yaml) ---


def create_test_gpkg(filepath: str, table_name: str = "test_layer", records: list[dict] | None = None) -> str:
    """
    Create a test GeoPackage with the schema used in workflow tests.

    Args:
        filepath: Path to create the GeoPackage.
        table_name: Name of the feature table.
        records: List of dicts with keys: name, PROGRESSIVO_ACCESSO, PROGRESSIVO_NAZIONALE

    Returns:
        Path to the created file.
    """
    if records is None:
        records = [
            {"name": "Point A", "PROGRESSIVO_ACCESSO": 1, "PROGRESSIVO_NAZIONALE": 101},
            {"name": "Point B", "PROGRESSIVO_ACCESSO": 2, "PROGRESSIVO_NAZIONALE": 202},
        ]

    conn = sqlite3.connect(filepath)
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        );
        CREATE TABLE gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT UNIQUE,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
            srs_id INTEGER
        );
        CREATE TABLE gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name)
        );
        INSERT INTO gpkg_spatial_ref_sys VALUES (
            'WGS 84', 4326, 'EPSG', 4326,
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
            NULL
        );
    """)

    cursor.execute(f"""
        CREATE TABLE {table_name} (
            geom BLOB,
            name TEXT,
            PROGRESSIVO_ACCESSO INTEGER,
            PROGRESSIVO_NAZIONALE INTEGER,
            PRIMARY KEY (PROGRESSIVO_ACCESSO, PROGRESSIVO_NAZIONALE)
        )
    """)

    cursor.execute(
        "INSERT INTO gpkg_contents VALUES (?, 'features', ?, '', datetime('now'), NULL, NULL, NULL, NULL, 4326)",
        (table_name, table_name),
    )
    cursor.execute(
        "INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', 'POINT', 4326, 0, 0)",
        (table_name,),
    )

    for record in records:
        cursor.execute(
            f"INSERT INTO {table_name} (name, PROGRESSIVO_ACCESSO, PROGRESSIVO_NAZIONALE) VALUES (?, ?, ?)",
            (record["name"], record["PROGRESSIVO_ACCESSO"], record["PROGRESSIVO_NAZIONALE"]),
        )

    conn.commit()
    conn.close()
    return filepath


def create_duckdb_from_gpkg(duckdb_path: str, gpkg_path: str, table_name: str = "test_layer") -> str:
    """Import a GeoPackage table into DuckDB."""
    with duckdb.connect(duckdb_path) as conn:
        conn.execute("INSTALL sqlite; LOAD sqlite;")
        conn.execute(
            f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM sqlite_scan(?, ?);", [gpkg_path, table_name]
        )
    return duckdb_path


def init_git_repo(repo_path: str) -> None:
    """Initialize a git repository with basic config."""
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)


def git_add_and_commit(repo_path: str, files: list[str], message: str) -> None:
    """Add files and commit."""
    for f in files:
        subprocess.run(["git", "add", f], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True, capture_output=True)


@pytest.fixture
def test_data_dir():
    """Create a temporary directory for test data."""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestTableExistsInDuckdb:
    """Tests for table_exists_in_duckdb function."""

    def test_table_exists(self, test_data_dir):
        """Test that existing table is detected."""
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = str(test_data_dir / "test.duckdb")

        create_test_gpkg(gpkg_path)
        create_duckdb_from_gpkg(duckdb_path, gpkg_path)

        assert table_exists_in_duckdb(Path(duckdb_path), "test_layer") is True

    def test_table_not_exists(self, test_data_dir):
        """Test that nonexistent table returns False."""
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = str(test_data_dir / "test.duckdb")

        create_test_gpkg(gpkg_path)
        create_duckdb_from_gpkg(duckdb_path, gpkg_path)

        assert table_exists_in_duckdb(Path(duckdb_path), "nonexistent_table") is False


class TestExtractTableFromDuckdb:
    """Tests for extract_table_from_duckdb function."""

    def test_extract_to_gpkg(self, test_data_dir):
        """Test extracting a table to GPKG format."""
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = str(test_data_dir / "test.duckdb")
        output_path = test_data_dir / "output.gpkg"

        create_test_gpkg(gpkg_path)
        create_duckdb_from_gpkg(duckdb_path, gpkg_path)

        # Change to test_data_dir for the extraction (temp file is created in cwd)
        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = extract_table_from_duckdb(
                duckdb_path=Path(duckdb_path),
                table_name="test_layer",
                output_path=output_path,
                output_format="GPKG",
                fid_column="PROGRESSIVO_ACCESSO",
            )
        finally:
            os.chdir(original_cwd)

        assert result.success is True
        assert result.output_path == output_path
        assert output_path.exists()

        # Verify the table exists in the output GPKG
        with sqlite3.connect(str(output_path)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            count = cursor.fetchone()[0]
            assert count == 2

    def test_extract_nonexistent_table_fails(self, test_data_dir):
        """Test that extracting a nonexistent table fails gracefully."""
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = str(test_data_dir / "test.duckdb")
        output_path = test_data_dir / "output.gpkg"

        create_test_gpkg(gpkg_path)
        create_duckdb_from_gpkg(duckdb_path, gpkg_path)

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = extract_table_from_duckdb(
                duckdb_path=Path(duckdb_path),
                table_name="nonexistent_table",
                output_path=output_path,
                output_format="GPKG",
                fid_column="PROGRESSIVO_ACCESSO",
            )
        finally:
            os.chdir(original_cwd)

        assert result.success is False
        assert result.error is not None


class TestApplyPrimaryKey:
    """Tests for apply_primary_key function."""

    def test_apply_primary_key_to_gpkg(self, test_data_dir):
        """Test applying primary key to a GPKG file."""
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = str(test_data_dir / "test.duckdb")
        output_path = test_data_dir / "output.gpkg"

        create_test_gpkg(gpkg_path)
        create_duckdb_from_gpkg(duckdb_path, gpkg_path)

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = extract_table_from_duckdb(
                duckdb_path=Path(duckdb_path),
                table_name="test_layer",
                output_path=output_path,
                output_format="GPKG",
                fid_column="PROGRESSIVO_ACCESSO",
            )
        finally:
            os.chdir(original_cwd)

        assert result.success is True

        # Apply primary key
        apply_primary_key(
            gpkg_path=output_path,
            table_name="test_layer",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        # Verify the table still has data after PK modification
        with sqlite3.connect(str(output_path)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            count = cursor.fetchone()[0]
            assert count == 2

            # Verify primary key columns are correctly set
            cursor = conn.execute("PRAGMA table_info(test_layer)")
            columns_info = cursor.fetchall()
            # PRAGMA table_info returns: (cid, name, type, notnull, dflt_value, pk)
            # pk > 0 indicates the column is part of the primary key
            pk_columns = [col[1] for col in columns_info if col[5] > 0]
            assert set(pk_columns) == {"PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"}


class TestRunExtractionIntegration:
    """Integration tests for run_extraction inspired by workflow tests."""

    def test_extract_first_commit_single_commit(self, test_data_dir):
        """
        Test extraction when table exists only in a single (first) commit.
        Inspired by: test-extract-first-commit workflow job.
        """
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = test_data_dir / "test.duckdb"

        create_test_gpkg(gpkg_path)
        create_duckdb_from_gpkg(str(duckdb_path), gpkg_path)

        # Initialize git repo with single commit
        init_git_repo(str(test_data_dir))
        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add base duckdb")

        config = ExtractionConfig(
            duckdb_file=str(duckdb_path),
            table_name="test_layer",
            output_format="GPKG",
            fid_column="PROGRESSIVO_ACCESSO",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = run_extraction(config, PrintLogger())
        finally:
            os.chdir(original_cwd)

        assert result.success is True
        assert result.current_file is not None
        assert result.current_file.exists()
        assert result.is_first_commit is True
        assert result.previous_file is None

        # Verify output file name pattern
        assert "test_layer-current.gpkg" in str(result.current_file)

    def test_extract_between_commits(self, test_data_dir):
        """
        Test extraction with changes between two commits.
        Inspired by: test-extract-between-commit workflow job.
        """
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = test_data_dir / "test.duckdb"

        # Create initial data
        create_test_gpkg(gpkg_path)
        create_duckdb_from_gpkg(str(duckdb_path), gpkg_path)

        # Initialize git repo with first commit
        init_git_repo(str(test_data_dir))
        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add base duckdb")

        # Modify data - delete, update, insert
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute("DELETE FROM test_layer WHERE PROGRESSIVO_ACCESSO = 2")
            conn.execute("UPDATE test_layer SET name = 'Point A Modified' WHERE PROGRESSIVO_ACCESSO = 1")
            conn.execute(
                "INSERT INTO test_layer (name, PROGRESSIVO_ACCESSO, PROGRESSIVO_NAZIONALE) VALUES ('Point C', 3, 303)"
            )

        # Second commit
        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Modify duckdb")

        config = ExtractionConfig(
            duckdb_file=str(duckdb_path),
            table_name="test_layer",
            output_format="GPKG",
            fid_column="PROGRESSIVO_ACCESSO",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = run_extraction(config, PrintLogger())
        finally:
            os.chdir(original_cwd)

        assert result.success is True
        assert result.current_file is not None
        assert result.current_file.exists()
        assert result.is_first_commit is False
        assert result.previous_file is not None
        assert result.previous_file.exists()

        # Verify output file name patterns
        assert "test_layer-current.gpkg" in str(result.current_file)
        assert "test_layer-previous.gpkg" in str(result.previous_file)

        # Verify current file has 2 records (1 original + 1 new - 1 deleted)
        with sqlite3.connect(str(result.current_file)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            assert cursor.fetchone()[0] == 2

        # Verify previous file has 2 records (original)
        with sqlite3.connect(str(result.previous_file)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            assert cursor.fetchone()[0] == 2

    def test_extract_table_added_after_multiple_commits(self, test_data_dir):
        """
        Test extraction when table is added after multiple commits already exist.
        Inspired by: test-extract-first-insert-in-various-commits workflow job.
        """
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = test_data_dir / "test.duckdb"

        # Initialize git repo
        init_git_repo(str(test_data_dir))

        # Create DuckDB with a different table first (not test_layer)
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute("CREATE TABLE another_table (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO another_table (id, value) VALUES (1, 'Value 1')")

        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add another_table")

        # Second commit - more data to another_table
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute("INSERT INTO another_table (id, value) VALUES (2, 'Value 2')")

        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Insert more into another_table")

        # Third commit - add test_layer
        create_test_gpkg(gpkg_path)
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute("INSTALL sqlite; LOAD sqlite;")
            conn.execute(
                "CREATE OR REPLACE TABLE test_layer AS SELECT * FROM sqlite_scan(?, 'test_layer');", [gpkg_path]
            )

        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add test_layer")

        config = ExtractionConfig(
            duckdb_file=str(duckdb_path),
            table_name="test_layer",
            output_format="GPKG",
            fid_column="PROGRESSIVO_ACCESSO",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = run_extraction(config, PrintLogger())
        finally:
            os.chdir(original_cwd)

        assert result.success is True
        assert result.current_file is not None
        assert result.current_file.exists()
        # Table didn't exist in previous commit, so it's treated as first commit for this table
        assert result.is_first_commit is True
        assert result.previous_file is None

    def test_extract_delete_records(self, test_data_dir):
        """
        Test extraction after deleting records.
        Inspired by: test-delete-check-with-geodiff workflow job.
        """
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = test_data_dir / "test.duckdb"

        # Create with 5 records
        records = [
            {"name": "Point A", "PROGRESSIVO_ACCESSO": 1, "PROGRESSIVO_NAZIONALE": 101},
            {"name": "Point B", "PROGRESSIVO_ACCESSO": 2, "PROGRESSIVO_NAZIONALE": 202},
            {"name": "Point C", "PROGRESSIVO_ACCESSO": 3, "PROGRESSIVO_NAZIONALE": 303},
            {"name": "Point D", "PROGRESSIVO_ACCESSO": 4, "PROGRESSIVO_NAZIONALE": 404},
            {"name": "Point E", "PROGRESSIVO_ACCESSO": 5, "PROGRESSIVO_NAZIONALE": 505},
        ]
        create_test_gpkg(gpkg_path, records=records)
        create_duckdb_from_gpkg(str(duckdb_path), gpkg_path)

        init_git_repo(str(test_data_dir))
        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add base duckdb with 5 records")

        # Delete 2 records
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute("DELETE FROM test_layer WHERE PROGRESSIVO_ACCESSO = 2 OR PROGRESSIVO_ACCESSO = 4")

        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Delete 2 records")

        config = ExtractionConfig(
            duckdb_file=str(duckdb_path),
            table_name="test_layer",
            output_format="GPKG",
            fid_column="PROGRESSIVO_ACCESSO",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = run_extraction(config, PrintLogger())
        finally:
            os.chdir(original_cwd)

        assert result.success is True

        # Verify current has 3 records
        with sqlite3.connect(str(result.current_file)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            assert cursor.fetchone()[0] == 3

        # Verify previous has 5 records
        with sqlite3.connect(str(result.previous_file)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            assert cursor.fetchone()[0] == 5

    def test_extract_update_records(self, test_data_dir):
        """
        Test extraction after updating records.
        Inspired by: test-update-check-with-geodiff workflow job.
        """
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = test_data_dir / "test.duckdb"

        records = [
            {"name": "Point A", "PROGRESSIVO_ACCESSO": 1, "PROGRESSIVO_NAZIONALE": 101},
            {"name": "Point B", "PROGRESSIVO_ACCESSO": 2, "PROGRESSIVO_NAZIONALE": 202},
            {"name": "Point C", "PROGRESSIVO_ACCESSO": 3, "PROGRESSIVO_NAZIONALE": 303},
        ]
        create_test_gpkg(gpkg_path, records=records)
        create_duckdb_from_gpkg(str(duckdb_path), gpkg_path)

        init_git_repo(str(test_data_dir))
        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add base duckdb")

        # Update 2 records
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute("UPDATE test_layer SET name = 'Updated Point A' WHERE PROGRESSIVO_ACCESSO = 1")
            conn.execute("UPDATE test_layer SET name = 'Updated Point C' WHERE PROGRESSIVO_ACCESSO = 3")

        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Update 2 records")

        config = ExtractionConfig(
            duckdb_file=str(duckdb_path),
            table_name="test_layer",
            output_format="GPKG",
            fid_column="PROGRESSIVO_ACCESSO",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = run_extraction(config, PrintLogger())
        finally:
            os.chdir(original_cwd)

        assert result.success is True

        # Both should have same count
        with sqlite3.connect(str(result.current_file)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            assert cursor.fetchone()[0] == 3

        with sqlite3.connect(str(result.previous_file)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            assert cursor.fetchone()[0] == 3

        # Verify current has updated names
        with sqlite3.connect(str(result.current_file)) as conn:
            cursor = conn.execute("SELECT name FROM test_layer WHERE PROGRESSIVO_ACCESSO = 1")
            assert cursor.fetchone()[0] == "Updated Point A"

        # Verify previous has original names
        with sqlite3.connect(str(result.previous_file)) as conn:
            cursor = conn.execute("SELECT name FROM test_layer WHERE PROGRESSIVO_ACCESSO = 1")
            assert cursor.fetchone()[0] == "Point A"

    def test_extract_insert_records(self, test_data_dir):
        """
        Test extraction after inserting new records.
        Inspired by: test-insert-check-with-geodiff workflow job.
        """
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = test_data_dir / "test.duckdb"

        records = [
            {"name": "Point A", "PROGRESSIVO_ACCESSO": 1, "PROGRESSIVO_NAZIONALE": 101},
            {"name": "Point B", "PROGRESSIVO_ACCESSO": 2, "PROGRESSIVO_NAZIONALE": 202},
        ]
        create_test_gpkg(gpkg_path, records=records)
        create_duckdb_from_gpkg(str(duckdb_path), gpkg_path)

        init_git_repo(str(test_data_dir))
        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add base duckdb")

        # Insert 2 new records
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute(
                "INSERT INTO test_layer (name, PROGRESSIVO_ACCESSO, PROGRESSIVO_NAZIONALE) VALUES ('Point C', 3, 303)"
            )
            conn.execute(
                "INSERT INTO test_layer (name, PROGRESSIVO_ACCESSO, PROGRESSIVO_NAZIONALE) VALUES ('Point D', 4, 404)"
            )

        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Insert 2 new records")

        config = ExtractionConfig(
            duckdb_file=str(duckdb_path),
            table_name="test_layer",
            output_format="GPKG",
            fid_column="PROGRESSIVO_ACCESSO",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = run_extraction(config, PrintLogger())
        finally:
            os.chdir(original_cwd)

        assert result.success is True

        # Verify current has 4 records
        with sqlite3.connect(str(result.current_file)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            assert cursor.fetchone()[0] == 4

        # Verify previous has 2 records
        with sqlite3.connect(str(result.previous_file)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM test_layer")
            assert cursor.fetchone()[0] == 2


# --- Geodiff Integration Tests ---


def get_geodiff_path() -> Path:
    """Get the path to the geodiff executable."""
    return Path(__file__).parent.parent / "tools" / "geodiff"


def run_geodiff_summary(previous_file: Path, current_file: Path) -> dict:
    """
    Run geodiff diff --summary and return the parsed JSON output.

    Args:
        previous_file: Path to the previous GeoPackage file.
        current_file: Path to the current GeoPackage file.

    Returns:
        Parsed JSON dict from geodiff output.
    """
    import json

    geodiff_path = get_geodiff_path()
    result = subprocess.run(
        [str(geodiff_path), "diff", "--summary", str(previous_file), str(current_file)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture
def geodiff_available():
    """Check if geodiff is available and skip test if not."""
    geodiff_path = get_geodiff_path()
    if not geodiff_path.exists():
        pytest.skip("geodiff tool not available")
    return geodiff_path


class TestGeodiffIntegration:
    """Integration tests that verify extraction results using geodiff."""

    def test_delete_records_with_geodiff(self, test_data_dir, geodiff_available):
        """
        Test extraction after deleting records and verify with geodiff.
        Mirrors: test-delete-check-with-geodiff workflow job.
        """
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = test_data_dir / "test.duckdb"

        # Create with 5 records
        records = [
            {"name": "Point A", "PROGRESSIVO_ACCESSO": 1, "PROGRESSIVO_NAZIONALE": 101},
            {"name": "Point B", "PROGRESSIVO_ACCESSO": 2, "PROGRESSIVO_NAZIONALE": 202},
            {"name": "Point C", "PROGRESSIVO_ACCESSO": 3, "PROGRESSIVO_NAZIONALE": 303},
            {"name": "Point D", "PROGRESSIVO_ACCESSO": 4, "PROGRESSIVO_NAZIONALE": 404},
            {"name": "Point E", "PROGRESSIVO_ACCESSO": 5, "PROGRESSIVO_NAZIONALE": 505},
        ]
        create_test_gpkg(gpkg_path, records=records)
        create_duckdb_from_gpkg(str(duckdb_path), gpkg_path)

        init_git_repo(str(test_data_dir))
        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add base duckdb with 5 records")

        # Delete 2 records (PROGRESSIVO_ACCESSO 2 and 4)
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute("DELETE FROM test_layer WHERE PROGRESSIVO_ACCESSO = 2 OR PROGRESSIVO_ACCESSO = 4")

        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Delete 2 records")

        config = ExtractionConfig(
            duckdb_file=str(duckdb_path),
            table_name="test_layer",
            output_format="GPKG",
            fid_column="PROGRESSIVO_ACCESSO",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = run_extraction(config, PrintLogger())
        finally:
            os.chdir(original_cwd)

        assert result.success is True
        assert result.previous_file is not None
        assert result.current_file is not None

        # Run geodiff and verify the summary
        geodiff_output = run_geodiff_summary(result.previous_file, result.current_file)

        # Expected: 2 deletes, 0 inserts, 0 updates
        summary = geodiff_output.get("geodiff_summary", [])
        assert len(summary) == 1
        table_summary = summary[0]
        assert table_summary["table"] == "test_layer"
        assert table_summary["delete"] == 2
        assert table_summary["insert"] == 0
        assert table_summary["update"] == 0

    def test_update_records_with_geodiff(self, test_data_dir, geodiff_available):
        """
        Test extraction after updating records and verify with geodiff.
        Mirrors: test-update-check-with-geodiff workflow job.
        """
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = test_data_dir / "test.duckdb"

        records = [
            {"name": "Point A", "PROGRESSIVO_ACCESSO": 1, "PROGRESSIVO_NAZIONALE": 101},
            {"name": "Point B", "PROGRESSIVO_ACCESSO": 2, "PROGRESSIVO_NAZIONALE": 202},
            {"name": "Point C", "PROGRESSIVO_ACCESSO": 3, "PROGRESSIVO_NAZIONALE": 303},
            {"name": "Point D", "PROGRESSIVO_ACCESSO": 4, "PROGRESSIVO_NAZIONALE": 404},
            {"name": "Point E", "PROGRESSIVO_ACCESSO": 5, "PROGRESSIVO_NAZIONALE": 505},
        ]
        create_test_gpkg(gpkg_path, records=records)
        create_duckdb_from_gpkg(str(duckdb_path), gpkg_path)

        init_git_repo(str(test_data_dir))
        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add base duckdb with 5 records")

        # Update 2 records (PROGRESSIVO_ACCESSO 2 and 4)
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute("UPDATE test_layer SET name = 'Updated Point B' WHERE PROGRESSIVO_ACCESSO = 2")
            conn.execute("UPDATE test_layer SET name = 'Updated Point D' WHERE PROGRESSIVO_ACCESSO = 4")

        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Update 2 records")

        config = ExtractionConfig(
            duckdb_file=str(duckdb_path),
            table_name="test_layer",
            output_format="GPKG",
            fid_column="PROGRESSIVO_ACCESSO",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = run_extraction(config, PrintLogger())
        finally:
            os.chdir(original_cwd)

        assert result.success is True
        assert result.previous_file is not None
        assert result.current_file is not None

        # Run geodiff and verify the summary
        geodiff_output = run_geodiff_summary(result.previous_file, result.current_file)

        # Expected: 0 deletes, 0 inserts, 2 updates
        summary = geodiff_output.get("geodiff_summary", [])
        assert len(summary) == 1
        table_summary = summary[0]
        assert table_summary["table"] == "test_layer"
        assert table_summary["delete"] == 0
        assert table_summary["insert"] == 0
        assert table_summary["update"] == 2

    def test_insert_records_with_geodiff(self, test_data_dir, geodiff_available):
        """
        Test extraction after inserting records and verify with geodiff.
        Mirrors: test-insert-check-with-geodiff workflow job.
        """
        gpkg_path = str(test_data_dir / "base.gpkg")
        duckdb_path = test_data_dir / "test.duckdb"

        records = [
            {"name": "Point A", "PROGRESSIVO_ACCESSO": 1, "PROGRESSIVO_NAZIONALE": 101},
            {"name": "Point B", "PROGRESSIVO_ACCESSO": 2, "PROGRESSIVO_NAZIONALE": 202},
            {"name": "Point C", "PROGRESSIVO_ACCESSO": 3, "PROGRESSIVO_NAZIONALE": 303},
            {"name": "Point D", "PROGRESSIVO_ACCESSO": 4, "PROGRESSIVO_NAZIONALE": 404},
            {"name": "Point E", "PROGRESSIVO_ACCESSO": 5, "PROGRESSIVO_NAZIONALE": 505},
        ]
        create_test_gpkg(gpkg_path, records=records)
        create_duckdb_from_gpkg(str(duckdb_path), gpkg_path)

        init_git_repo(str(test_data_dir))
        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Add base duckdb with 5 records")

        # Insert 2 new records
        with duckdb.connect(str(duckdb_path)) as conn:
            conn.execute(
                "INSERT INTO test_layer (name, PROGRESSIVO_ACCESSO, PROGRESSIVO_NAZIONALE) VALUES ('Inserted Point F', 6, 606)"
            )
            conn.execute(
                "INSERT INTO test_layer (name, PROGRESSIVO_ACCESSO, PROGRESSIVO_NAZIONALE) VALUES ('Inserted Point G', 7, 707)"
            )

        git_add_and_commit(str(test_data_dir), ["test.duckdb"], "Insert 2 new records")

        config = ExtractionConfig(
            duckdb_file=str(duckdb_path),
            table_name="test_layer",
            output_format="GPKG",
            fid_column="PROGRESSIVO_ACCESSO",
            primary_key_columns=["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"],
        )

        original_cwd = os.getcwd()
        os.chdir(test_data_dir)
        try:
            result = run_extraction(config, PrintLogger())
        finally:
            os.chdir(original_cwd)

        assert result.success is True
        assert result.previous_file is not None
        assert result.current_file is not None

        # Run geodiff and verify the summary
        geodiff_output = run_geodiff_summary(result.previous_file, result.current_file)

        # Expected: 0 deletes, 2 inserts, 0 updates
        summary = geodiff_output.get("geodiff_summary", [])
        assert len(summary) == 1
        table_summary = summary[0]
        assert table_summary["table"] == "test_layer"
        assert table_summary["delete"] == 0
        assert table_summary["insert"] == 2
        assert table_summary["update"] == 0
