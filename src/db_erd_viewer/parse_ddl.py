#!/usr/bin/env python3
"""
parse_ddl.py

Convierte uno o más archivos .sql (DDL / migraciones) en el JSON intermedio
que consume render_erd.py. Usa sqlglot para parsear un AST real en vez de
regex, así que soporta múltiples dialectos y ambos estilos de FK:

    -- column-level
    user_id UUID REFERENCES users(id)

    -- table-level
    FOREIGN KEY (user_id) REFERENCES users(id)

Limitaciones conocidas (v1):
    - FKs compuestas (multi-columna) no se soportan: se ignoran con un
      warning en stderr en vez de fallar silenciosamente.
    - ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY (típico en migraciones
      separadas por archivo) todavía no se procesa — solo CREATE TABLE.
      Es el siguiente caso a cubrir si tu proyecto usa ese patrón.

Uso:
    python parse_ddl.py schema.sql -o schema.json
    python parse_ddl.py migrations/*.sql --dialect mysql -o schema.json
"""
import argparse
import json
import sys

import sqlglot
from sqlglot import exp


def parse_ddl(sql_text, dialect="postgres"):
    tables = []
    warnings = []

    try:
        statements = sqlglot.parse(sql_text, dialect=dialect)
    except Exception as e:
        raise SystemExit(f"Error parseando DDL con dialecto '{dialect}': {e}")

    for stmt in statements:
        if not isinstance(stmt, exp.Create) or stmt.kind != "TABLE":
            continue

        table_expr = stmt.find(exp.Table)
        if table_expr is None:
            continue
        table_name = table_expr.name

        schema_expr = stmt.this
        columns = []
        table_level_fks = []   # (local_col, ref_table, ref_col)
        table_level_pks = []

        for e in schema_expr.expressions:
            if isinstance(e, exp.ColumnDef):
                col_name = e.name
                kind = e.args.get("kind")
                type_sql = kind.sql(dialect=dialect).lower() if kind else "unknown"

                pk, nullable, fk = False, True, None
                for c in e.args.get("constraints", []):
                    ckind = c.kind
                    if isinstance(ckind, exp.PrimaryKeyColumnConstraint):
                        pk, nullable = True, False
                    elif isinstance(ckind, exp.NotNullColumnConstraint):
                        nullable = False
                    elif isinstance(ckind, exp.Reference):
                        ref_schema = ckind.this
                        ref_table = ref_schema.this.name
                        ref_cols = ref_schema.expressions
                        ref_col = ref_cols[0].name if ref_cols else "id"
                        fk = {"table": ref_table, "column": ref_col}

                col = {"name": col_name, "type": type_sql, "nullable": nullable}
                if pk:
                    col["pk"] = True
                if fk:
                    col["fk"] = fk
                columns.append(col)

            elif isinstance(e, exp.ForeignKey):
                local_cols = [i.name for i in e.expressions]
                ref = e.args.get("reference")
                if ref is None:
                    continue
                ref_schema = ref.this
                ref_table = ref_schema.this.name
                ref_cols = ref_schema.expressions
                ref_col = ref_cols[0].name if ref_cols else "id"
                if len(local_cols) == 1:
                    table_level_fks.append((local_cols[0], ref_table, ref_col))
                else:
                    warnings.append(
                        f"tabla '{table_name}': FK compuesta ({', '.join(local_cols)}) "
                        f"ignorada — no soportada en v1"
                    )

            elif isinstance(e, exp.PrimaryKey):
                table_level_pks.extend(i.name for i in e.expressions)

        col_by_name = {c["name"]: c for c in columns}
        for local_col, ref_table, ref_col in table_level_fks:
            if local_col in col_by_name:
                col_by_name[local_col]["fk"] = {"table": ref_table, "column": ref_col}
            else:
                warnings.append(f"tabla '{table_name}': FK referencia columna desconocida '{local_col}'")
        for pk_col in table_level_pks:
            if pk_col in col_by_name:
                col_by_name[pk_col]["pk"] = True
                col_by_name[pk_col]["nullable"] = False

        if not columns:
            continue
        tables.append({"name": table_name, "columns": columns})

    # segunda pasada: ALTER TABLE ... ADD [CONSTRAINT ...] FOREIGN KEY (...)
    # REFERENCES ...(...) — patrón común cuando las migraciones agregan las
    # FKs por separado de la creación de la tabla (Rails, Django, Prisma, etc.)
    tables_by_name = {t["name"]: t for t in tables}
    for stmt in statements:
        if not isinstance(stmt, exp.Alter) or stmt.kind != "TABLE":
            continue
        table_expr = stmt.this
        table_name = table_expr.name if table_expr else None
        target = tables_by_name.get(table_name)
        if target is None:
            warnings.append(f"ALTER TABLE referencia tabla desconocida '{table_name}' — ignorado")
            continue

        for action in stmt.args.get("actions", []):
            if not isinstance(action, exp.AddConstraint):
                continue
            for item in action.expressions:
                fk_expr = item if isinstance(item, exp.ForeignKey) else (
                    next((c for c in item.expressions if isinstance(c, exp.ForeignKey)), None)
                    if isinstance(item, exp.Constraint) else None
                )
                if fk_expr is None:
                    continue
                local_cols = [i.name for i in fk_expr.expressions]
                ref = fk_expr.args.get("reference")
                if ref is None or len(local_cols) != 1:
                    if len(local_cols) > 1:
                        warnings.append(
                            f"tabla '{table_name}': FK compuesta vía ALTER TABLE "
                            f"({', '.join(local_cols)}) ignorada — no soportada en v1"
                        )
                    continue
                ref_schema = ref.this
                ref_table = ref_schema.this.name
                ref_cols = ref_schema.expressions
                ref_col = ref_cols[0].name if ref_cols else "id"

                col_by_name = {c["name"]: c for c in target["columns"]}
                local_col = local_cols[0]
                if local_col in col_by_name:
                    col_by_name[local_col]["fk"] = {"table": ref_table, "column": ref_col}
                else:
                    warnings.append(
                        f"tabla '{table_name}': ALTER TABLE referencia columna desconocida '{local_col}'"
                    )

    return tables, warnings


def build_schema_from_files(paths, dialect="postgres"):
    """Lee uno o más .sql, parsea y devuelve (schema_dict, warnings)."""
    raw_ddl = "\n\n".join(open(p).read() for p in paths)
    tables, warnings = parse_ddl(raw_ddl, dialect=dialect)
    return {"raw_ddl": raw_ddl, "tables": tables}, warnings


def main():
    ap = argparse.ArgumentParser(description="Parsea DDL .sql al JSON intermedio del ERD viewer")
    ap.add_argument("sql_files", nargs="+", help="uno o más archivos .sql")
    ap.add_argument("--dialect", default="postgres",
                     help="dialecto SQL (postgres, mysql, sqlite, tsql, ...). Default: postgres")
    ap.add_argument("-o", "--output", default="schema.json")
    args = ap.parse_args()

    raw_ddl_parts = []
    for path in args.sql_files:
        with open(path) as f:
            raw_ddl_parts.append(f.read())
    raw_ddl = "\n\n".join(raw_ddl_parts)

    tables, warnings = parse_ddl(raw_ddl, dialect=args.dialect)

    for w in warnings:
        print(f"[warning] {w}", file=sys.stderr)

    if not tables:
        print("[warning] no se encontró ningún CREATE TABLE en los archivos dados", file=sys.stderr)

    schema = {"raw_ddl": raw_ddl, "tables": tables}
    with open(args.output, "w") as f:
        json.dump(schema, f, indent=2)

    print(f"Parseadas {len(tables)} tablas -> {args.output}")


if __name__ == "__main__":
    main()
