from typing import List


def set_primary_key(table_name: str, primary_key_columns: List[str], conn) -> None:
    """duplicate a table into GPKG adding primary keys

    Args:
        table_name (str): Name of the table to replicate
        primary_key_columns (List[str]): List of columns to set as primary key
        con (_type_): Database connection object
    """
    temp_table_name = f"{table_name}_temp_pk"
    conn.execute("BEGIN TRANSACTION;")
    # get schema of existing table
    result = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?;", (table_name,)
    ).fetchone()
    if not result:
        raise ValueError(f"Table {table_name} does not exist.")

    # modify schema to remove fid as primary key
    # an example of schema string is: CREATE TABLE cities ( fid INTEGER PRIMARY KEY AUTOINCREMENT, geom BLOB, name TEXT NOT NULL, description TEXT, population INTEGER, elevation_m REAL )
    # and new schema should be: CREATE TABLE cities_temp_pk ( fid INTEGER, geom BLOB, name TEXT NOT NULL, description TEXT, population INTEGER, elevation_m REAL, PRIMARY KEY(fid, name) )
    create_table_sql = result[0]
    import re

    # Remove inline 'PRIMARY KEY' or 'PRIMARY KEY AUTOINCREMENT' tokens in column definitions
    create_table_sql_no_pk = re.sub(
        r"\bPRIMARY\s+KEY(?:\s+AUTOINCREMENT)?\b", "", create_table_sql, flags=re.IGNORECASE
    )
    # Also remove table-level primary key clauses like ', PRIMARY KEY(col1, col2)'
    create_table_sql_no_pk = re.sub(r",\s*PRIMARY\s+KEY\s*\([^)]+\)", "", create_table_sql_no_pk, flags=re.IGNORECASE)
    # Normalize any accidental multiple spaces introduced
    create_table_sql_no_pk = re.sub(r"\s{2,}", " ", create_table_sql_no_pk)

    # add new primary keys at the end of the create table statement
    create_table_sql_with_new_pk = (
        create_table_sql_no_pk.rstrip(" );") + f", PRIMARY KEY({', '.join(primary_key_columns)}) );"
    )

    # create new table with modified schema
    conn.execute(create_table_sql_with_new_pk.replace(table_name, temp_table_name))
    # copy data into new table
    q = f"INSERT INTO {temp_table_name} SELECT * FROM {table_name};"
    conn.execute(q)

    # drop old table and rename new table
    conn.execute(f"DROP TABLE {table_name};")
    q = f"ALTER TABLE {temp_table_name} RENAME TO {table_name};"
    conn.execute(q)
    conn.execute("COMMIT;")
