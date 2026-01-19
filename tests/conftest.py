"""Pytest configuration and fixtures for geodiff tests."""

import shutil
import sqlite3
import struct
import tempfile
from pathlib import Path

import pytest

# reusing subset of conftest from geodiff-action codebase


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)


def create_gpkg_point_geometry(lon: float, lat: float, srs_id: int = 4326) -> bytes:
    """
    Create a GeoPackage-compliant point geometry in WKB format.

    Args:
        lon: Longitude (X coordinate) in degrees.
        lat: Latitude (Y coordinate) in degrees.
        srs_id: Spatial Reference System ID (default: 4326 for WGS84).

    Returns:
        Binary GeoPackage geometry (GP header + WKB).
    """
    # GeoPackage binary header
    # Magic number: 'GP' (0x4750)
    # Version: 0
    # Flags: 0x01 (little-endian WKB, no envelope)
    # SRS ID: 4 bytes
    gp_header = b"GP"
    gp_header += struct.pack("<bb", 0, 1)  # Version 0, flags
    gp_header += struct.pack("<i", srs_id)  # SRS ID

    # WKB Point geometry (little-endian)
    # Byte order: 1 (little-endian)
    # Geometry type: 1 (Point)
    # X coordinate: 8 bytes double
    # Y coordinate: 8 bytes double
    wkb = struct.pack("<bI", 1, 1)  # Little-endian, Point type
    wkb += struct.pack("<dd", lon, lat)  # X (lon), Y (lat)

    return gp_header + wkb


def create_geopackage(
    filepath: str,
    table_name: str = "locations",
    features: list[dict] | None = None,
    description: str = "Test GeoPackage",
) -> str:
    """
    Create a GeoPackage file with point features representing real geographic locations.

    Args:
        filepath: Path where to create the GeoPackage.
        table_name: Name of the feature table.
        features: List of feature dicts with keys:
            - id: Feature ID (optional, auto-generated if not provided)
            - name: Location name
            - lon: Longitude in degrees
            - lat: Latitude in degrees
            - description: Optional description
        description: Description for the GeoPackage contents.

    Returns:
        Path to the created GeoPackage.
    """
    if features is None:
        features = []

    conn = sqlite3.connect(filepath)
    cursor = conn.cursor()

    # Create GeoPackage required metadata tables (OGC GeoPackage spec)
    cursor.executescript("""
        -- Spatial Reference Systems table
        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        );

        -- Contents table (registry of all tables)
        CREATE TABLE IF NOT EXISTS gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT UNIQUE,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE,
            min_y DOUBLE,
            max_x DOUBLE,
            max_y DOUBLE,
            srs_id INTEGER,
            CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
        );

        -- Geometry columns table
        CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
            CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
            CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
        );

        -- Insert WGS84 spatial reference system (EPSG:4326)
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, organization_coordsys_id, definition, description)
        VALUES (
            'WGS 84 geodetic',
            4326,
            'EPSG',
            4326,
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]',
            'longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid'
        );

        -- Insert undefined Cartesian SRS
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, organization_coordsys_id, definition)
        VALUES ('Undefined cartesian SRS', -1, 'NONE', -1, 'undefined');

        -- Insert undefined geographic SRS
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization, organization_coordsys_id, definition)
        VALUES ('Undefined geographic SRS', 0, 'NONE', 0, 'undefined');
    """)

    # Create the feature table with geographic attributes
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            fid INTEGER PRIMARY KEY AUTOINCREMENT,
            geom BLOB,
            name TEXT NOT NULL,
            description TEXT,
            population INTEGER,
            elevation_m REAL
        )
    """)

    # Calculate bounding box from features
    if features:
        min_x = min(f.get("lon", 0) for f in features)
        max_x = max(f.get("lon", 0) for f in features)
        min_y = min(f.get("lat", 0) for f in features)
        max_y = max(f.get("lat", 0) for f in features)
    else:
        min_x = max_x = min_y = max_y = None

    # Register in gpkg_contents
    cursor.execute(
        """
        INSERT OR REPLACE INTO gpkg_contents (table_name, data_type, identifier, description, srs_id, min_x, min_y, max_x, max_y)
        VALUES (?, 'features', ?, ?, 4326, ?, ?, ?, ?)
        """,
        (table_name, table_name, description, min_x, min_y, max_x, max_y),
    )

    # Register in gpkg_geometry_columns
    cursor.execute(
        """
        INSERT OR REPLACE INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m)
        VALUES (?, 'geom', 'POINT', 4326, 0, 0)
        """,
        (table_name,),
    )

    # Insert features with real geographic data
    for feature in features:
        fid = feature.get("id")
        name = feature.get("name", "Unknown")
        lon = feature.get("lon", 0.0)
        lat = feature.get("lat", 0.0)
        desc = feature.get("description", "")
        population = feature.get("population")
        elevation = feature.get("elevation_m")

        # Create GeoPackage point geometry
        gpkg_geom = create_gpkg_point_geometry(lon, lat)

        if fid is not None:
            cursor.execute(
                f"INSERT INTO {table_name} (fid, geom, name, description, population, elevation_m) VALUES (?, ?, ?, ?, ?, ?)",
                (fid, gpkg_geom, name, desc, population, elevation),
            )
        else:
            cursor.execute(
                f"INSERT INTO {table_name} (geom, name, description, population, elevation_m) VALUES (?, ?, ?, ?, ?)",
                (gpkg_geom, name, desc, population, elevation),
            )

    conn.commit()
    conn.close()

    return filepath


# Sample geographic data: Italian cities
ITALIAN_CITIES_BASE = [
    {
        "id": 1,
        "name": "Roma",
        "lon": 12.4964,
        "lat": 41.9028,
        "description": "Capital of Italy",
        "population": 2870500,
        "elevation_m": 21.0,
    },
    {
        "id": 2,
        "name": "Milano",
        "lon": 9.1900,
        "lat": 45.4642,
        "description": "Financial capital of Italy",
        "population": 1396059,
        "elevation_m": 120.0,
    },
    {
        "id": 3,
        "name": "Napoli",
        "lon": 14.2681,
        "lat": 40.8518,
        "description": "Major city in southern Italy",
        "population": 967068,
        "elevation_m": 17.0,
    },
    {
        "id": 4,
        "name": "Torino",
        "lon": 7.6869,
        "lat": 45.0703,
        "description": "Industrial city in northern Italy",
        "population": 870952,
        "elevation_m": 239.0,
    },
    {
        "id": 5,
        "name": "Firenze",
        "lon": 11.2558,
        "lat": 43.7696,
        "description": "Renaissance art capital",
        "population": 382808,
        "elevation_m": 50.0,
    },
]


@pytest.fixture
def base_gpkg(temp_dir):
    """
    Create a base GeoPackage with Italian cities.

    Contains 5 cities: Roma, Milano, Napoli, Torino, Firenze
    """
    filepath = temp_dir / "italian_cities_base.gpkg"
    return create_geopackage(
        str(filepath),
        table_name="cities",
        features=ITALIAN_CITIES_BASE,
        description="Italian cities dataset - Base version",
    )
