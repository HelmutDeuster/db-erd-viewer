---
name: db-erd-viewer
description: Genera un diagrama entidad-relación (ERD) visual e interactivo de una base de datos, como un único archivo HTML autocontenido con SVG custom (no Mermaid) y el DDL de referencia al lado. Las líneas de foreign key se dibujan a nivel de columna, no solo tabla-a-tabla, para máxima precisión visual. Soporta dos fuentes de schema — archivos DDL/migraciones (.sql) del proyecto, o conexión directa a una base de datos viva (SQLite, Postgres, MySQL). Usar esta skill SIEMPRE que el usuario pida ver, visualizar, diagramar, documentar o entender la estructura de una base de datos o sus relaciones — frases como "muéstrame el ERD", "diagrama la base de datos", "visualiza el schema", "quiero ver cómo se relacionan las tablas", "genera documentación de la BBDD", o cuando el usuario está escribiendo queries con JOINs y necesita referencia visual rápida de las foreign keys. También activar si el usuario menciona archivos de migración/DDL y quiere entender sus relaciones, o si pide conectarse a una base de datos para ver su estructura.
---

# db-erd-viewer

Genera un ERD visual e interactivo (zoom, pan, reposicionar tablas, hover para
resaltar FKs, modo selección para armar queries con JOINs automáticos) más un
panel de DDL de referencia, todo en un único archivo HTML sin dependencias
externas ni servidor.

## Arquitectura (léelo antes de improvisar)

Todo pasa por un JSON intermedio (ver `references/schema_format.md` para el
formato exacto). Hay dos formas de llegar a ese JSON, y una sola forma de
convertirlo en HTML — todo detrás de un único comando instalable, `db-erd-viewer`
(mismo paquete Python, usable tanto por esta skill como desde una terminal
normal fuera de Claude Code):

```
archivos .sql  ──►┐
                    ├──► `db-erd-viewer` ──► JSON intermedio ──► erd.html
BBDD viva      ──►┘
```

No hay que elegir entre "parsear DDL" o "conectar a la BBDD" a nivel de
diseño — son dos caminos intercambiables al mismo formato, seleccionados con
`--sql` o `--db` en el mismo comando. Si no es obvio cuál quiere el usuario,
preguntá: "¿querés que lea los archivos de DDL/migraciones del proyecto, o
que me conecte directo a la base de datos?"

### Instalación (una sola vez por proyecto/entorno)

```bash
pip install -e /path/to/db-erd-viewer --break-system-packages
# o, si ya está publicada en GitHub:
pip install "db-erd-viewer[all] @ git+https://github.com/<usuario>/db-erd-viewer.git" --break-system-packages
```

Verificar con `db-erd-viewer --help`. Si el comando no aparece en el PATH,
usar `python -m db_erd_viewer.cli` como alternativa equivalente.

### Uso: un solo paso (lo más común)

```bash
db-erd-viewer generate --sql schema.sql -o erd.html
db-erd-viewer generate --sql migrations/*.sql --dialect mysql -o erd.html
db-erd-viewer generate --db sqlite --sqlite-path ./app.db -o erd.html
db-erd-viewer generate --db postgres --host localhost --database mydb --user postgres -o erd.html
db-erd-viewer generate --db mysql --host localhost --database mydb --user root -o erd.html
```

`--dialect` acepta lo que soporta `sqlglot` (postgres, mysql, sqlite, tsql,
etc.). Default: `postgres`.

**Credenciales**: si se omite `--password`, el comando la pide de forma
interactiva (no queda en el historial de la shell). Nunca hardcodees una
password en un script que vayas a commitear, y no la escribas en el JSON
intermedio ni en el HTML de salida.

Dependencias opcionales según motor — instalar solo la que haga falta (o
`pip install -e ".[all]"` para tener las tres):
```bash
pip install -e ".[postgres]" --break-system-packages   # psycopg2-binary
pip install -e ".[mysql]" --break-system-packages      # pymysql
# sqlite no necesita nada extra (stdlib)
```

### Uso: dos pasos (cuando conviene inspeccionar el JSON intermedio)

```bash
db-erd-viewer to-json --sql schema.sql -o schema.json
# inspeccionar/editar schema.json si hace falta
db-erd-viewer render schema.json -o erd.html
```

Si el JSON no trae posiciones manuales por tabla (el caso normal), el
auto-layout corre solo al renderizar — no hace falta ningún paso adicional.
El usuario puede reacomodar tablas a mano arrastrando el header una vez
abierto el HTML; esos cambios no se guardan entre regeneraciones (es una
skill on-demand, sin estado persistente).

## Paso 3: entregar

Guardar el HTML final donde el usuario lo pueda abrir fácilmente (por defecto
en el directorio de trabajo actual como `erd.html`, o donde el usuario pida).
Contarle brevemente qué puede hacer con él, sin asumir que ya lo sabe la
primera vez:

- Scroll para zoom, arrastrar el fondo para desplazarse
- Arrastrar el título de una tabla para moverla
- Click en el título de una tabla → ver solo su DDL (+ botón para sumar relacionadas)
- Switch "Modo selección" → click en columnas arma un `SELECT` con los `JOIN`s automáticos (soporta multi-hop vía FKs intermedias)

## Limitaciones conocidas (comunicárselas al usuario si son relevantes al caso)

- FKs compuestas (multi-columna) no se dibujan — ver `references/schema_format.md`.
- `parse_ddl.py` no procesa `ALTER TABLE ... ADD CONSTRAINT` si la tabla
  referenciada no apareció antes en el mismo archivo/conjunto de archivos.
- La introspección de Postgres asume schema `public` salvo que se pase `--schema`.
- El auto-layout es un spring model simple; en schemas grandes (50+ tablas)
  puede dejar mucho espacio vacío entre clusters — el zoom/pan y el
  reposicionamiento manual son la mitigación actual, no hay agrupado por
  dominio automático todavía.

## Archivos de este skill

```
pyproject.toml               — hace el paquete instalable, expone el comando `db-erd-viewer`
src/db_erd_viewer/
  cli.py                      — punto de entrada (subcomandos generate/to-json/render)
  parse_ddl.py                — .sql -> JSON intermedio (usa sqlglot)
  introspect_db.py            — BBDD viva -> JSON intermedio (sqlite/postgres/mysql)
  layout.py                   — auto-layout (interno, no se invoca directo)
  render_erd.py               — JSON intermedio -> HTML final
references/
  schema_format.md            — spec completa del JSON intermedio
examples/
  example_schema.json         — 4 tablas, para pruebas rápidas
  example_schema_large.json   — 18 tablas, para probar el auto-layout
```

Este mismo paquete es tanto la skill de Claude Code como la herramienta CLI
standalone — no hay dos implementaciones separadas que mantener en paralelo.
