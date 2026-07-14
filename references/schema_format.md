# Formato del JSON intermedio

Tanto `parse_ddl.py` como `introspect_db.py` producen (y `render_erd.py` consume)
el mismo formato. Esto es lo que desacopla la fuente del schema (DDL o BBDD
viva) del renderizado — el renderer no sabe ni le importa de dónde vino el JSON.

```json
{
  "raw_ddl": "CREATE TABLE users (...);\n\nCREATE TABLE orders (...);",
  "tables": [
    {
      "name": "orders",
      "position": {"x": 40, "y": 320},
      "columns": [
        {"name": "id", "type": "uuid", "pk": true, "nullable": false},
        {"name": "user_id", "type": "uuid", "nullable": false,
         "fk": {"table": "users", "column": "id"}}
      ]
    }
  ]
}
```

## Campos

- **`raw_ddl`** (string, opcional): texto a mostrar en el panel de DDL. Si viene
  de `parse_ddl.py` es el `.sql` original tal cual. Si viene de
  `introspect_db.py` es DDL *sintetizado* desde la introspección (no reproduce
  exactamente el DDL original — no incluye índices, checks, ni defaults
  complejos — pero es suficiente como referencia legible).

- **`tables[].name`** (string): nombre de la tabla, debe ser único.

- **`tables[].position`** (objeto, **opcional**): `{"x": num, "y": num}`.
  Si **cualquier** tabla del JSON no trae `position`, `render_erd.py` ignora
  las posiciones de *todas* las tablas y corre el auto-layout completo
  (ver `scripts/layout.py`). No hay soporte todavía para mezclar posiciones
  manuales fijas con auto-layout parcial — es todo o nada en v1.

- **`tables[].columns[].name`** (string)

- **`tables[].columns[].type`** (string): tipo SQL tal cual, en minúsculas
  (ej. `"varchar(120)"`, `"numeric(10,2)"`, `"uuid"`).

- **`tables[].columns[].nullable`** (bool)

- **`tables[].columns[].pk`** (bool, opcional): omitido si es `false`.

- **`tables[].columns[].fk`** (objeto, opcional): `{"table": "...", "column": "..."}`.
  Apunta a la tabla y columna referenciada. El renderer usa esto para dibujar
  la línea de conexión al nivel exacto de esa fila — es la pieza central de
  todo el proyecto.

## Limitaciones conocidas (compartidas por ambas fuentes)

- **FKs compuestas (multi-columna) no se soportan.** Tanto `parse_ddl.py` como
  la introspección las detectan y las ignoran con un warning en stderr, en vez
  de fallar silenciosamente o romper el parseo del resto del schema.
- Un `fk` solo puede apuntar a una columna. Si tu schema tiene FKs compuestas
  reales, van a faltar esas líneas en el diagrama — es una limitación conocida,
  no un bug.
