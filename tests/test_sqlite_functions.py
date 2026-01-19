"""Tests for src/functions.py"""

import sys

sys.path.insert(0, "src")

from sqlite_functions import set_primary_key


class TestSetPrimaryKey:
    """Tests for the set_primary_key function."""

    def test_set_primary_key(self, base_gpkg):
        """Test that set_primary_key duplicate table adding primary keys."""
        import sqlite3

        conn = sqlite3.connect(str(base_gpkg))

        # check that current primary key is just "fid"
        result = conn.execute("PRAGMA table_info(cities);").fetchall()
        pk_columns_before = [row[1] for row in result if row[5] > 0]
        assert pk_columns_before == ["fid"]

        # get all rows before
        original_rows = conn.execute("SELECT * FROM cities;").fetchall()

        # reset pks
        table_name = "cities"
        primary_key_columns = ["fid", "name"]
        set_primary_key(table_name, primary_key_columns, conn)

        # check that new primary keys are set
        result = conn.execute(f"PRAGMA table_info({table_name});").fetchall()
        print(f"Table info after setting PKs: {result}")
        pk_columns = [row[1] for row in result if row[5] > 0]
        assert pk_columns == primary_key_columns

        # check the content is the same
        new_rows = conn.execute("SELECT * FROM cities;").fetchall()
        for original_row in original_rows:
            assert original_row in new_rows

        conn.close()
