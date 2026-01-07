#!/usr/bin/env python3

# Extract DuckDB Tables Action
# This action extracts specified tables from a DuckDB database file
# and saves them in the desired format (GPKG or Parquet).
# two versions of the table are extracted: current and previous (if available)
# where previous refers to the version in the previous commit.

import json
import subprocess
from pathlib import Path

from actions import context, core

import functions
from git_utils import GitError, find_repo_root, get_file_from_commit, get_previous_commit, has_file_in_commit

# Configure git to trust all directories (needed for Docker containers)
# This must be done early before any git operations
subprocess.run(
    ["git", "config", "--global", "--add", "safe.directory", "*"],
    capture_output=True,
    check=False,
)

version: str = core.get_version()
core.info(f"Starting Extract DuckDB Tables Action - \033[32;1m{version}")


# Inputs

duckdb_file: str = core.get_input("duckdb_file", True)
core.info(f"duckdb_file: \033[36;1m{duckdb_file}")
table_name: str = core.get_input("table_name", True)
core.info(f"table_name: \033[36;1m{table_name}")
output_format: str = core.get_input("output_format") or "GPKG"
core.info(f"output_format: \033[35;1m{output_format}")
token: str = core.get_input("token", True)

# Debug

with core.group("uv"):
    functions.check_output("uv -V", False)
    functions.check_output("uv python dir", False)


ctx = {k: v for k, v in vars(context).items() if not k.startswith("__")}
del ctx["os"]
with core.group("GitHub Context Data"):
    core.debug(json.dumps(ctx, indent=4))


# Action Logic

core.info("Extracting DuckDB tables...")

# Track temp files for cleanup
temp_files_to_cleanup: list[str] = []

# Initialize variables
duckdb_file_path = Path(duckdb_file).resolve()
if not duckdb_file_path.exists():
    core.set_failed(f"DuckDB file does not exist: {duckdb_file_path}")
    raise SystemExit(1)
table_name_safe = "".join(c if c.isalnum() else "_" for c in table_name)
current_file_name = f"{duckdb_file_path.stem}-{table_name_safe}-current"
previous_file_name = f"{duckdb_file_path.stem}-{table_name_safe}-previous"
if output_format.upper() == "GPKG":
    current_file_name += ".gpkg"
    previous_file_name += ".gpkg"
elif output_format.upper() == "PARQUET":
    current_file_name += ".parquet"
    previous_file_name += ".parquet"
else:
    core.set_failed(f"Unsupported output format: {output_format}")
    raise SystemExit(1)

# Extract paths from duckdb_file_path
output_file_path: Path = duckdb_file_path.parent / current_file_name
previous_file_path: Path = duckdb_file_path.parent / previous_file_name
# Extract current table
core.info(f"Extracting current table '{table_name}' from {duckdb_file_path} to {output_file_path}...")
try:
    import duckdb

    with duckdb.connect(database=str(duckdb_file_path), read_only=True) as conn:
        # conn.execute(
        #     "COPY (SELECT * FROM \"?\") TO ? (FORMAT ?);", [f'"{table_name}"', f"'{str(output_file_path)}'", f"'{output_format.lower()}'"],
        # )
        conn.execute("INSTALL spatial;")
        conn.execute("LOAD spatial;")
        conn.execute(
            f"COPY (SELECT * FROM \"{table_name}\") TO '{str(output_file_path)}' (FORMAT 'GDAL', DRIVER '{output_format.upper()}');"
        )
        core.info(f"Extracted table '{table_name}' to {output_file_path}")

        # check that output file was created
        if not output_file_path.exists():
            core.set_failed(f"Output file was not created: {output_file_path}")
            raise SystemExit(1)

except Exception as e:
    core.set_failed(f"Failed to extract table '{table_name}': {e}")
    raise SystemExit(1) from e
finally:
    # Cleanup temp files
    for temp_file in temp_files_to_cleanup:
        try:
            Path(temp_file).unlink(missing_ok=True)
        except Exception:
            pass

core.info("Current table extraction completed SUCCESSFULLY")

# Check for previous commit and extract previous table if possible
try:
    repo_root = find_repo_root(str(duckdb_file_path.parent))
    previous_commit = get_previous_commit(repo_root, offset=1) if repo_root else None
    if (
        repo_root
        and previous_commit
        and has_file_in_commit(repo_root, str(duckdb_file_path.relative_to(repo_root)), previous_commit)
    ):
        core.info(f"Found previous commit: {previous_commit}")
        previous_duckdb_path = get_file_from_commit(
            repo_root,
            str(duckdb_file_path.relative_to(repo_root)),
            previous_commit,
        )

        # check if previous_duckdb_path exists
        if not Path(previous_duckdb_path).exists():
            core.set_failed(f"Previous DuckDB file was not extracted: {previous_duckdb_path}")
            raise SystemExit(1)

        # remember to cleanup temp duckdb file
        # temp_files_to_cleanup.append(str(previous_duckdb_path))

        core.info(f"Extracting previous table '{table_name}' from {previous_duckdb_path} to {previous_file_path}...")
        with duckdb.connect(database=str(previous_duckdb_path), read_only=True) as con_prev:
            con_prev.execute("INSTALL spatial;")
            con_prev.execute("LOAD spatial;")
            con_prev.execute(
                f"COPY (SELECT * FROM \"{table_name}\") TO '{str(previous_file_path)}' (FORMAT 'GDAL', DRIVER '{output_format.upper()}');"
            )
            core.info(f"Extracted previous table '{table_name}' to {previous_file_path}")

            # check that previous output file was created
            if not previous_file_path.exists():
                core.set_failed(f"Previous output file was not created: {previous_file_path}")
                raise SystemExit(1)

        # diff beween current extracted file and previous version si delgated to a different action
    else:
        core.info(
            f"No previous commit with the DuckDB file {duckdb_file_path} found; skipping previous table extraction."
        )

except GitError as ge:
    core.set_failed(f"Git error occurred: {ge}")
    raise SystemExit(1) from ge
except Exception as e:
    core.set_failed(f"An error occurred during previous extraction or diffing: {e}")
    raise SystemExit(1) from e
finally:
    # Cleanup temp files
    for temp_file in temp_files_to_cleanup:
        try:
            Path(temp_file).unlink(missing_ok=True)
        except Exception:
            pass

    # set outputs in the github context
    core.info("Setting action outputs...")
    core.set_output("current_file", str(output_file_path))
    core.info(f"Set current_file output: {str(output_file_path)}")
    if previous_file_path.exists():
        core.set_output("previous_file", str(previous_file_path))
        core.info(f"Set previous_file output: {str(previous_file_path)}")
    else:
        core.info("No previous_file output set (file does not exist)")

core.info("Extract DuckDB Tables Action completed")
print("\033[32;1mExtract DuckDB Tables Action completed successfully\033[0m")
