#!/usr/bin/env python3
"""
introspect_db.py

Conecta a una BBDD real y produce el mismo JSON intermedio que parse_ddl.py
genera a partir de archivos .sql. Soporta sqlite, postgres y mysql.

Estado de validación (importante, léelo antes de confiar ciegamente):
    - sqlite: probado end-to-end contra un archivo .db real en este entorno.
    - postgres: implementado contra las queries estándar de information_schema
      documentadas por Postgres. NO se pudo levantar un servidor Postgres en
      este sandbox para probarlo contra una conexión real — revisar con
      cuidado la primera vez que se use contra una BBDD real.
    - mysql: mismo caso que postgres — implementado pero no probado contra un
      servidor real.

Dependencias opcionales (solo se importan si se usa ese motor):
    - postgres: psycopg2-binary
    - mysql:    pymysql

Uso:
    python introspect_db.py --engine sqlite --sqlite-path ./mydb.db -o schema.json
    python introspect_db.py --engine postgres --host localhost --database mydb \\
        --user postgres --password secret -o schema.json
    python introspect_db.py --engine mysql --host localhost --database mydb \\
        --user root --password secret -o schema.json
"""
import argparse
import json
import sys


# ---------- SQLite ----------

def introspect_sqlite(path):
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    table_names = [row[0] for row in cur.fetchall()]

    tables = []
    for name in table_names:
        cur.execute(f'PRAGMA table_info("{name}")')
        # (cid, name, type, notnull, dflt_value, pk)
        col_rows = cur.fetchall()

        cur.execute(f'PRAGMA foreign_key_list("{name}")')
        # (id, seq, table, from, to, on_update, on_delete, match)
        fk_rows = cur.fetchall()
        fk_by_col = {row[3]: {"table": row[2], "column": row[4]} for row in fk_rows}

        columns = []
        for cid, col_name, col_type, notnull, default, pk in col_rows:
            col = {
                "name": col_name,
                "type": (col_type or "unknown").lower(),
                "nullable": not bool(notnull) and not bool(pk),
            }
            if pk:
                col["pk"] = True
            if col_name in fk_by_col:
                col["fk"] = fk_by_col[col_name]
            columns.append(col)

        tables.append({"name": name, "columns": columns})

    conn.close()
    return tables


# ---------- Postgres ----------

def introspect_postgres(host, port, database, user, password, schema):
    try:
        import psycopg2
    except ImportError:
        raise SystemExit(
            "Falta psycopg2. Instalar con: pip install psycopg2-binary --break-system-packages"
        )

    conn = psycopg2.connect(host=host, port=port or 5432, dbname=database, user=user, password=password)
    cur = conn.cursor()

    cur.execute("""
        SELECT table_name, column_name, data_type, character_maximum_length,
               numeric_precision, numeric_scale, is_nullable, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position
    """, (schema,))
    col_rows = cur.fetchall()

    cur.execute("""
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = %s
    """, (schema,))
    pk_set = {(row[0], row[1]) for row in cur.fetchall()}

    cur.execute("""
        SELECT kcu.table_name, kcu.column_name, ccu.table_name, ccu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s
    """, (schema,))
    fk_map = {(row[0], row[1]): {"table": row[2], "column": row[3]} for row in cur.fetchall()}

    conn.close()
    return _rows_to_tables(col_rows, pk_set, fk_map)


# ---------- MySQL ----------

def introspect_mysql(host, port, database, user, password):
    try:
        import pymysql
    except ImportError:
        raise SystemExit("Falta pymysql. Instalar con: pip install pymysql --break-system-packages")

    conn = pymysql.connect(host=host, port=port or 3306, database=database, user=user, password=password)
    cur = conn.cursor()

    cur.execute("""
        SELECT table_name, column_name, data_type, character_maximum_length,
               numeric_precision, numeric_scale, is_nullable, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position
    """, (database,))
    col_rows = cur.fetchall()

    cur.execute("""
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = %s
    """, (database,))
    pk_set = {(row[0], row[1]) for row in cur.fetchall()}

    # MySQL expone directamente referenced_table_name/referenced_column_name
    # en key_column_usage — no necesita el join extra que sí hace falta en Postgres.
    cur.execute("""
        SELECT table_name, column_name, referenced_table_name, referenced_column_name
        FROM information_schema.key_column_usage
        WHERE referenced_table_name IS NOT NULL AND table_schema = %s
    """, (database,))
    fk_map = {(row[0], row[1]): {"table": row[2], "column": row[3]} for row in cur.fetchall()}

    conn.close()
    return _rows_to_tables(col_rows, pk_set, fk_map)


def _format_type(data_type, char_len, num_precision, num_scale):
    dt = (data_type or "unknown").lower()
    if char_len:
        return f"{dt}({char_len})"
    if dt in ("numeric", "decimal") and num_precision is not None:
        if num_scale:
            return f"{dt}({num_precision},{num_scale})"
        return f"{dt}({num_precision})"
    return dt


def _rows_to_tables(col_rows, pk_set, fk_map):
    tables_dict = {}
    for table_name, col_name, data_type, char_len, num_prec, num_scale, is_nullable, _ord in col_rows:
        table = tables_dict.setdefault(table_name, {"name": table_name, "columns": []})
        col = {
            "name": col_name,
            "type": _format_type(data_type, char_len, num_prec, num_scale),
            "nullable": (is_nullable == "YES"),
        }
        if (table_name, col_name) in pk_set:
            col["pk"] = True
            col["nullable"] = False
        if (table_name, col_name) in fk_map:
            col["fk"] = fk_map[(table_name, col_name)]
        table["columns"].append(col)
    return list(tables_dict.values())


# ---------- DDL sintética (para el panel de referencia, ya que no hay .sql original) ----------

def synthesize_ddl(tables):
    blocks = []
    for t in tables:
        lines = []
        for c in t["columns"]:
            parts = [c["name"], c["type"]]
            if c.get("pk"):
                parts.append("PRIMARY KEY")
            elif not c.get("nullable", True):
                parts.append("NOT NULL")
            if "fk" in c:
                parts.append(f'REFERENCES {c["fk"]["table"]}({c["fk"]["column"]})')
            lines.append("  " + " ".join(parts))
        blocks.append(f"CREATE TABLE {t['name']} (\n" + ",\n".join(lines) + "\n);")
    return "\n\n".join(blocks)


def build_schema_from_db(engine, **kwargs):
    """
    kwargs esperados según engine:
      sqlite:   sqlite_path
      postgres: host, port, database, user, password, schema
      mysql:    host, port, database, user, password
    Devuelve schema_dict (con raw_ddl sintetizado).
    """
    if engine == "sqlite":
        tables = introspect_sqlite(kwargs["sqlite_path"])
    elif engine == "postgres":
        tables = introspect_postgres(
            kwargs.get("host", "localhost"), kwargs.get("port"), kwargs["database"],
            kwargs["user"], kwargs.get("password"), kwargs.get("schema", "public"),
        )
    elif engine == "mysql":
        tables = introspect_mysql(
            kwargs.get("host", "localhost"), kwargs.get("port"), kwargs["database"],
            kwargs["user"], kwargs.get("password"),
        )
    else:
        raise ValueError(f"engine desconocido: {engine}")
    return {"raw_ddl": synthesize_ddl(tables), "tables": tables}


def main():
    ap = argparse.ArgumentParser(description="Introspección de BBDD viva al JSON intermedio del ERD viewer")
    ap.add_argument("--engine", required=True, choices=["sqlite", "postgres", "mysql"])
    ap.add_argument("--sqlite-path", help="ruta al archivo .db (solo engine=sqlite)")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int)
    ap.add_argument("--database", help="nombre de la base (postgres/mysql)")
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--schema", default="public", help="schema (solo postgres, default 'public')")
    ap.add_argument("-o", "--output", default="schema.json")
    args = ap.parse_args()

    if args.engine == "sqlite":
        if not args.sqlite_path:
            raise SystemExit("--sqlite-path es requerido para engine=sqlite")
        tables = introspect_sqlite(args.sqlite_path)
    elif args.engine == "postgres":
        if not (args.database and args.user):
            raise SystemExit("--database y --user son requeridos para engine=postgres")
        tables = introspect_postgres(args.host, args.port, args.database, args.user, args.password, args.schema)
    elif args.engine == "mysql":
        if not (args.database and args.user):
            raise SystemExit("--database y --user son requeridos para engine=mysql")
        tables = introspect_mysql(args.host, args.port, args.database, args.user, args.password)
    else:
        raise SystemExit(f"engine desconocido: {args.engine}")

    if not tables:
        print("[warning] no se encontraron tablas — revisa el schema/database indicado", file=sys.stderr)

    schema = {"raw_ddl": synthesize_ddl(tables), "tables": tables}
    with open(args.output, "w") as f:
        json.dump(schema, f, indent=2)

    print(f"Introspectadas {len(tables)} tablas ({args.engine}) -> {args.output}")


if __name__ == "__main__":
    main()
