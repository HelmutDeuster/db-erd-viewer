#!/usr/bin/env python3
"""
cli.py — punto de entrada único del paquete, expuesto como el comando
`db-erd-viewer` una vez instalado (`pip install .` / `pipx install .`).

Subcomandos:
    db-erd-viewer generate --sql schema.sql -o erd.html
    db-erd-viewer generate --db sqlite --sqlite-path app.db -o erd.html
    db-erd-viewer generate --db postgres --host localhost --database mydb --user postgres -o erd.html
    db-erd-viewer to-json --sql schema.sql -o schema.json      # solo el JSON intermedio
    db-erd-viewer render schema.json -o erd.html                # solo renderizar un JSON ya existente

`generate` es el atajo de un solo paso (lo más cómodo desde la terminal).
`to-json` + `render` por separado son útiles para inspeccionar o versionar
el JSON intermedio entre pasos — es el mismo flujo de dos pasos que usa
Claude Code al invocar esta skill.
"""
import argparse
import getpass
import json
import sys

from . import parse_ddl as parse_ddl_mod
from . import introspect_db as introspect_db_mod
from . import render_erd as render_erd_mod


def _add_source_args(p):
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--sql", nargs="+", metavar="FILE", help="uno o más archivos .sql")
    src.add_argument("--db", choices=["sqlite", "postgres", "mysql"], help="conectar a una BBDD viva")

    p.add_argument("--dialect", default="postgres", help="dialecto SQL para --sql (default: postgres)")

    p.add_argument("--sqlite-path", help="ruta al .db (--db sqlite)")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int)
    p.add_argument("--database", help="nombre de la base (--db postgres/mysql)")
    p.add_argument("--user")
    p.add_argument("--password", help="si se omite y hace falta, se pide interactivamente")
    p.add_argument("--schema", default="public", help="schema de Postgres (default: public)")


def _build_schema(args):
    if args.sql:
        schema, warnings = parse_ddl_mod.build_schema_from_files(args.sql, dialect=args.dialect)
        for w in warnings:
            print(f"[warning] {w}", file=sys.stderr)
        return schema

    engine = args.db
    if engine == "sqlite":
        if not args.sqlite_path:
            raise SystemExit("--sqlite-path es requerido con --db sqlite")
        return introspect_db_mod.build_schema_from_db("sqlite", sqlite_path=args.sqlite_path)

    if not (args.database and args.user):
        raise SystemExit(f"--database y --user son requeridos con --db {engine}")
    password = args.password
    if password is None:
        password = getpass.getpass(f"Password para {args.user}@{args.host}: ")
    return introspect_db_mod.build_schema_from_db(
        engine, host=args.host, port=args.port, database=args.database,
        user=args.user, password=password, schema=args.schema,
    )


def cmd_generate(args):
    schema = _build_schema(args)
    html_out = render_erd_mod.render_schema_to_html(schema, title=args.output)
    with open(args.output, "w") as f:
        f.write(html_out)
    print(f"{len(schema['tables'])} tablas -> {args.output}")


def cmd_to_json(args):
    schema = _build_schema(args)
    with open(args.output, "w") as f:
        json.dump(schema, f, indent=2)
    print(f"{len(schema['tables'])} tablas -> {args.output}")


def cmd_render(args):
    with open(args.schema_json) as f:
        schema = json.load(f)
    html_out = render_erd_mod.render_schema_to_html(schema, title=args.schema_json)
    with open(args.output, "w") as f:
        f.write(html_out)
    print(f"Escrito {args.output}")


def main():
    ap = argparse.ArgumentParser(prog="db-erd-viewer")
    sub = ap.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="fuente (.sql o BBDD viva) -> erd.html en un solo paso")
    _add_source_args(p_gen)
    p_gen.add_argument("-o", "--output", default="erd.html")
    p_gen.set_defaults(func=cmd_generate)

    p_json = sub.add_parser("to-json", help="fuente -> JSON intermedio (sin renderizar)")
    _add_source_args(p_json)
    p_json.add_argument("-o", "--output", default="schema.json")
    p_json.set_defaults(func=cmd_to_json)

    p_render = sub.add_parser("render", help="JSON intermedio -> erd.html")
    p_render.add_argument("schema_json")
    p_render.add_argument("-o", "--output", default="erd.html")
    p_render.set_defaults(func=cmd_render)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
