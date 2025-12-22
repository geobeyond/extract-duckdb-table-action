# Extract tables from Duckdb Action

> Extract some configurable geo tables into gpkg file

A GitHub Action for extracting a configurable tables from a configurable duckdb. Extract just materialize the table into a GPKG

## Features

# Extract tables from DuckDB Action

Extract and convert tables from DuckDB files into GeoPackage (GPKG) or Parquet outputs. This repository contains an action and a workflow to extract a table from a DuckDB file changed in a commit or when run manually.

## Features

- Extract a named table from a DuckDB file using the DuckDB Python package
- Optionally convert the result to GPKG using `ogr2ogr` (GDAL)
- Triggered automatically on commits that modify `**/*.duckdb` files, or manually via `workflow_dispatch`

## Workflow

The workflow is defined in [.github/workflows/extract-duckdb.yml](.github/workflows/extract-duckdb.yml).

- Triggers: `push` on `**/*.duckdb` and `workflow_dispatch` for manual runs.
- Environment: `ubuntu-latest` runner (the workflow installs `gdal-bin` and the `duckdb` Python package).

### Inputs (manual run)

- `table_name` (required): table name to extract from the DuckDB file.
- `output_format` (optional): `GPKG` (default) or `PARQUET`.

### Behavior

- On push: the workflow locates the first `.duckdb` file changed in the commit and extracts the requested table.
- On manual dispatch: provide `table_name` (and optional `output_format`) in the Run workflow form.
- Outputs: the workflow writes an output file named `<duckdb-base>-<table>.(gpkg|parquet)` and sets `output_file` in the job outputs.

## Usage examples

Manual run (UI): go to the Actions tab, pick "Extract DuckDB Table", click "Run workflow" and set `table_name`.

Programmatic example (manual workflow_dispatch in another workflow using `workflow_call` or via API):

```yaml
# Example consumer workflow (concept)
name: Invoke Extract
on:
  workflow_dispatch:
    inputs:
      table_name:
        required: true
jobs:
  call:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger extract workflow (example)
        run: echo "Use repository dispatch or call the workflow from the UI with table_name=${{ github.event.inputs.table_name }}"
```

## Notes

- The workflow expects `table_name` via `workflow_dispatch` input or an environment variable; for fully automated push-based extraction you may add a small convention (file, metadata, or wrapper workflow) to provide the table name.
- Conversion to GPKG uses `ogr2ogr`; ensure your data schema is compatible with GDAL.

## Development

Follow the existing development instructions in this README for running tests and linters locally.
