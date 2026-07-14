# db-erd-viewer

Genera un diagrama entidad-relación (ERD) visual e interactivo de una base de
datos, como un único archivo HTML autocontenido — sin servidor, sin
dependencias en el navegador.

A diferencia de las herramientas basadas en Mermaid, las líneas de foreign key
se dibujan **a nivel de columna**, no solo tabla-a-tabla — así se ve
exactamente qué columna referencia a cuál.

El HTML generado incluye:
- Diagrama SVG con zoom, pan y tablas reposicionables a mano
- Panel de DDL de referencia, filtrable por tabla
- Modo selección: click en columnas arma un `SELECT` con los `JOIN`s
  correctos automáticamente (soporta relaciones multi-hop)

Funciona de dos formas, con el mismo paquete:
- **CLI standalone**, desde cualquier terminal
- **Skill de [Claude Code](https://docs.claude.com/claude-code)** — ver `SKILL.md`

## Instalación

```bash
pip install "db-erd-viewer[all] @ git+https://github.com/HelmutDeuster/db-erd-viewer.git"
```

O clonando el repo:
```bash
git clone https://github.com/HelmutDeuster/db-erd-viewer.git
cd db-erd-viewer
pip install -e ".[all]"
```

`[all]` instala los drivers de Postgres y MySQL. Si solo necesitás uno:
`pip install -e ".[postgres]"` o `pip install -e ".[mysql]"`. SQLite no
necesita nada extra (usa la librería estándar de Python).

## Uso

```bash
# desde un archivo DDL / migración
db-erd-viewer generate --sql schema.sql -o erd.html

# desde varios archivos, con dialecto explícito
db-erd-viewer generate --sql migrations/*.sql --dialect mysql -o erd.html

# desde una base de datos viva
db-erd-viewer generate --db sqlite --sqlite-path ./app.db -o erd.html
db-erd-viewer generate --db postgres --host localhost --database mydb --user postgres -o erd.html
db-erd-viewer generate --db mysql --host localhost --database mydb --user root -o erd.html
```

Si omitís `--password`, se pide de forma interactiva.

Para inspeccionar o versionar el JSON intermedio entre pasos:
```bash
db-erd-viewer to-json --sql schema.sql -o schema.json
db-erd-viewer render schema.json -o erd.html
```

## Formato del JSON intermedio

Ver [`references/schema_format.md`](references/schema_format.md).

## Limitaciones conocidas

- FKs compuestas (multi-columna) no se soportan — se detectan y se ignoran
  con un warning, no rompen el resto del parseo.
- La introspección de Postgres/MySQL usa las queries estándar de
  `information_schema`; probada contra Postgres 16 y MariaDB 10.11.
- El auto-layout es un spring model simple; en schemas muy grandes (50+
  tablas) puede dejar espacio vacío entre clusters — el zoom/pan y el
  reposicionamiento manual son la mitigación actual.
- Las posiciones movidas a mano en el HTML no se guardan entre regeneraciones.

## Licencia

MIT — ver [`LICENSE`](LICENSE).
