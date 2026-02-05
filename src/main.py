#!/usr/bin/env python3

# Extract DuckDB Tables Action
# This action extracts specified tables from a DuckDB database file
# and saves them in the desired format (GPKG or Parquet).
# two versions of the table are extracted: current and previous (if available)
# where previous refers to the version in the previous commit.

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import duckdb

from git_utils import GitError, find_repo_root, get_file_from_commit, get_previous_commit_for_file, has_file_in_commit
from sqlite_functions import set_primary_key


# --- Configuration ---


@dataclass
class ExtractionConfig:
    """Configuration for table extraction."""

    duckdb_file: str
    table_name: str
    output_format: str = "GPKG"
    fid_column: str = "PROGRESSIVO_ACCESSO"
    primary_key_columns: list[str] = field(default_factory=lambda: ["PROGRESSIVO_ACCESSO", "PROGRESSIVO_NAZIONALE"])

    def __post_init__(self) -> None:
        self.output_format = self.output_format.upper()
        if self.output_format not in ("GPKG", "PARQUET"):
            raise ValueError(f"Unsupported output format: {self.output_format}")


# --- Logger Protocol ---


class Logger(Protocol):
    """Protocol for logging - allows dependency injection for testing."""

    def info(self, message: str) -> None: ...
    def debug(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...
    def set_failed(self, message: str) -> None: ...
    def set_output(self, name: str, value: str) -> None: ...


class PrintLogger:
    """Simple logger that prints to stdout."""

    def info(self, message: str) -> None:
        print(f"[INFO] {message}")

    def debug(self, message: str) -> None:
        print(f"[DEBUG] {message}")

    def error(self, message: str) -> None:
        print(f"[ERROR] {message}")

    def set_failed(self, message: str) -> None:
        print(f"[FAILED] {message}")

    def set_output(self, name: str, value: str) -> None:
        print(f"[OUTPUT] {name}={value}")


# --- Result Types ---


@dataclass
class ExtractionResult:
    """Result of a table extraction operation."""

    success: bool
    output_path: Path | None = None
    error: str | None = None


@dataclass
class ActionResult:
    """Result of the entire action."""

    success: bool
    current_file: Path | None = None
    previous_file: Path | None = None
    is_first_commit: bool = False
    error: str | None = None


# --- Helper Functions ---


def sanitize_table_name(table_name: str) -> str:
    """Convert table name to a safe filename component."""
    return "".join(c if c.isalnum() else "_" for c in table_name)


def get_output_extension(output_format: str) -> str:
    """Get file extension for the given output format."""
    return ".gpkg" if output_format.upper() == "GPKG" else ".parquet"


def build_output_paths(
    duckdb_file_path: Path,
    table_name: str,
    output_format: str,
) -> tuple[Path, Path, str]:
    """
    Build output file paths for current and previous extractions.

    Returns:
        Tuple of (current_output_path, previous_output_path, tablebased_filename)
    """
    table_name_safe = sanitize_table_name(table_name)
    ext = get_output_extension(output_format)

    current_file_name = f"{duckdb_file_path.stem}-{table_name_safe}-current{ext}"
    previous_file_name = f"{duckdb_file_path.stem}-{table_name_safe}-previous{ext}"
    tablebased_file_name = f"{table_name_safe}{ext}"

    return (
        duckdb_file_path.parent / current_file_name,
        duckdb_file_path.parent / previous_file_name,
        tablebased_file_name,
    )


# --- Core Extraction Functions ---


def extract_table_from_duckdb(
    duckdb_path: Path,
    table_name: str,
    output_path: Path,
    output_format: str,
    fid_column: str,
    logger: Logger | None = None,
) -> ExtractionResult:
    """
    Extract a table from a DuckDB database to GPKG or Parquet format.

    Args:
        duckdb_path: Path to the DuckDB database file.
        table_name: Name of the table to extract.
        output_path: Path where the output file will be saved.
        output_format: Output format (GPKG or PARQUET).
        fid_column: Column to use as FID in GDAL export.
        logger: Optional logger for status messages.

    Returns:
        ExtractionResult indicating success/failure.
    """
    if logger:
        logger.info(f"Extracting table '{table_name}' from {duckdb_path} to {output_path}...")

    # Use a temp filename based on table name (required for GDAL layer naming)
    tablebased_filename = f"{sanitize_table_name(table_name)}{get_output_extension(output_format)}"

    try:
        with duckdb.connect(database=str(duckdb_path), read_only=True) as conn:
            conn.execute("INSTALL spatial;")
            conn.execute("LOAD spatial;")

            conn.execute(
                "COPY (SELECT * FROM query_table($1)) TO $2 (FORMAT 'GDAL', DRIVER $3, LAYER_CREATION_OPTIONS $4);",
                [table_name, tablebased_filename, output_format.upper(), f"FID={fid_column}"],
            )

            # Move to final output location
            Path(tablebased_filename).rename(output_path)

        if not output_path.exists():
            return ExtractionResult(success=False, error=f"Output file was not created: {output_path}")

        if logger:
            logger.info(f"Extracted table '{table_name}' to {output_path}")

        return ExtractionResult(success=True, output_path=output_path)

    except Exception as e:
        return ExtractionResult(success=False, error=str(e))


def table_exists_in_duckdb(duckdb_path: Path, table_name: str) -> bool:
    """Check if a table exists in a DuckDB database."""
    with duckdb.connect(database=str(duckdb_path), read_only=True) as conn:
        res = conn.execute(
            "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = $1;",
            [table_name],
        ).fetchone()
        return res is not None and res[0] > 0


def apply_primary_key(
    gpkg_path: Path,
    table_name: str,
    primary_key_columns: list[str],
    logger: Logger | None = None,
) -> None:
    """Apply primary key constraints to a GPKG table."""
    if logger:
        logger.info(f"Setting primary key on table '{table_name}' in {gpkg_path}...")

    with sqlite3.connect(str(gpkg_path)) as conn:
        set_primary_key(table_name, primary_key_columns, conn)


# --- Main Action Logic ---


def run_extraction(config: ExtractionConfig, logger: Logger | None = None) -> ActionResult:
    """
    Run the full extraction action.

    Args:
        config: Extraction configuration.
        logger: Optional logger for status messages.

    Returns:
        ActionResult with paths to extracted files.
    """
    duckdb_file_path = Path(config.duckdb_file).resolve()

    # Validate input file exists
    if not duckdb_file_path.exists():
        error = f"DuckDB file does not exist: {duckdb_file_path}"
        if logger:
            logger.set_failed(error)
        return ActionResult(success=False, error=error)

    # Build output paths
    output_file_path, previous_file_path, _ = build_output_paths(
        duckdb_file_path, config.table_name, config.output_format
    )

    # --- Extract current table ---
    if logger:
        logger.info("Extracting current table...")

    result = extract_table_from_duckdb(
        duckdb_path=duckdb_file_path,
        table_name=config.table_name,
        output_path=output_file_path,
        output_format=config.output_format,
        fid_column=config.fid_column,
        logger=logger,
    )

    if not result.success:
        error = f"Failed to extract table '{config.table_name}': {result.error}"
        if logger:
            logger.set_failed(error)
        return ActionResult(success=False, error=error)

    # Apply primary key to current table (GPKG only)
    if config.output_format == "GPKG":
        try:
            apply_primary_key(output_file_path, config.table_name, config.primary_key_columns, logger)
        except Exception as e:
            error = f"Failed to set primary key on current table: {e}"
            if logger:
                logger.set_failed(error)
            return ActionResult(success=False, error=error)

    if logger:
        logger.info("Current table extraction completed successfully")

    # --- Extract previous table (if available) ---
    is_first_commit = False
    previous_extracted: Path | None = None

    try:
        repo_root = find_repo_root(str(duckdb_file_path.parent))
        previous_commit = (
            get_previous_commit_for_file(repo_root, str(duckdb_file_path.relative_to(repo_root)), offset=1)
            if repo_root
            else None
        )

        if (
            repo_root
            and previous_commit
            and has_file_in_commit(repo_root, str(duckdb_file_path.relative_to(repo_root)), previous_commit)
        ):
            if logger:
                logger.info(f"Found previous commit: {previous_commit}")

            previous_duckdb_path = Path(
                get_file_from_commit(
                    repo_root,
                    str(duckdb_file_path.relative_to(repo_root)),
                    previous_commit,
                )
            )

            if not previous_duckdb_path.exists():
                error = f"Previous DuckDB file was not extracted: {previous_duckdb_path}"
                if logger:
                    logger.set_failed(error)
                return ActionResult(success=False, error=error)

            # Check if table exists in previous version
            if table_exists_in_duckdb(previous_duckdb_path, config.table_name):
                prev_result = extract_table_from_duckdb(
                    duckdb_path=previous_duckdb_path,
                    table_name=config.table_name,
                    output_path=previous_file_path,
                    output_format=config.output_format,
                    fid_column=config.fid_column,
                    logger=logger,
                )

                if not prev_result.success:
                    error = f"Failed to extract previous table: {prev_result.error}"
                    if logger:
                        logger.set_failed(error)
                    return ActionResult(success=False, error=error)

                # Apply primary key to previous table (GPKG only)
                if config.output_format == "GPKG":
                    apply_primary_key(previous_file_path, config.table_name, config.primary_key_columns, logger)

                previous_extracted = previous_file_path
            else:
                if logger:
                    logger.info(f"Table '{config.table_name}' does not exist in previous DuckDB; skipping.")
                is_first_commit = True
        else:
            if logger:
                logger.info("No previous commit with DuckDB file found; skipping previous table extraction.")
            is_first_commit = True

    except GitError as ge:
        error = f"Git error occurred: {ge}"
        if logger:
            logger.set_failed(error)
        return ActionResult(success=False, error=error)

    return ActionResult(
        success=True,
        current_file=output_file_path,
        previous_file=previous_extracted,
        is_first_commit=is_first_commit,
    )


def set_action_outputs(result: ActionResult, logger: Logger) -> None:
    """Set GitHub Action outputs based on the result."""
    logger.info("Setting action outputs...")

    if result.current_file:
        logger.set_output("current_file", str(result.current_file))
        logger.info(f"Set current_file output: {result.current_file}")

    if result.previous_file and result.previous_file.exists():
        logger.set_output("previous_file", str(result.previous_file))
        logger.info(f"Set previous_file output: {result.previous_file}")
    else:
        logger.set_output("previous_file", "first_commit")
        logger.info("Set previous_file output: first_commit")


# --- Entry Point ---


def main() -> None:
    """Main entry point for the GitHub Action."""
    import json
    import subprocess

    from actions import context, core

    import functions

    # Configure git to trust all directories (needed for Docker containers)
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", "*"],
        capture_output=True,
        check=False,
    )

    version: str = core.get_version()
    core.info(f"Starting Extract DuckDB Tables Action - \033[32;1m{version}")

    # Read inputs
    duckdb_file: str = core.get_input("duckdb_file", True)
    core.info(f"duckdb_file: \033[36;1m{duckdb_file}")
    table_name: str = core.get_input("table_name", True)
    core.info(f"table_name: \033[36;1m{table_name}")
    output_format: str = core.get_input("output_format") or "GPKG"
    core.info(f"output_format: \033[35;1m{output_format}")
    core.get_input("token", True)  # Validate token is present

    # Debug info
    with core.group("uv"):
        functions.check_output("uv -V", False)
        functions.check_output("uv python dir", False)

    ctx = {k: v for k, v in vars(context).items() if not k.startswith("__")}
    del ctx["os"]
    with core.group("GitHub Context Data"):
        core.debug(json.dumps(ctx, indent=4))

    # Create configuration
    config = ExtractionConfig(
        duckdb_file=duckdb_file,
        table_name=table_name,
        output_format=output_format,
    )

    # Create logger adapter for GitHub Actions core
    class GitHubActionsLogger:
        def info(self, message: str) -> None:
            core.info(message)

        def debug(self, message: str) -> None:
            core.debug(message)

        def error(self, message: str) -> None:
            core.error(message)

        def set_failed(self, message: str) -> None:
            core.set_failed(message)

        def set_output(self, name: str, value: str) -> None:
            core.set_output(name, value)

    logger = GitHubActionsLogger()

    # Run extraction
    core.info("Extracting DuckDB tables...")
    result = run_extraction(config, logger)

    if not result.success:
        raise SystemExit(1)

    # Set outputs
    set_action_outputs(result, logger)

    core.info("Extract DuckDB Tables Action completed")
    print("\033[32;1mExtract DuckDB Tables Action completed successfully\033[0m")


if __name__ == "__main__":
    main()
