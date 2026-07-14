#!/usr/bin/env python3
"""
render_erd.py

Convierte el JSON intermedio (ver references/schema_format.md) en un HTML
autocontenido: SVG custom del ERD (FKs a nivel de columna) + panel de DDL +
borrador de queries interactivo. Toda la interactividad es JS client-side
embebido — el HTML sigue siendo un solo archivo, sin server.

Modelo de interacción:
  - Hover sobre una fila -> resalta la(s) linea(s) de FK que la tocan.
  - Click en el HEADER de una tabla -> foco: muestra SOLO el DDL de esa tabla.
    "+ mostrar relacionadas" es una accion explicita aparte.
  - Arrastrar el HEADER de una tabla -> la reposiciona; las lineas de FK que
    la tocan se recalculan en vivo (mismo algoritmo de ruteo que el lado
    Python, portado a JS).
  - Scroll sobre el diagrama -> zoom centrado en el mouse. Arrastrar el fondo
    (no una tabla) -> pan. Botones +/-/reset como alternativa sin mouse wheel.
  - Modo seleccion (switch, off por default) -> click en filas arma el
    borrador de SELECT con JOINs via BFS sobre el grafo de FKs.
  - Boton "Copiar" en el borrador de query.

Uso:
    python render_erd.py example_schema.json -o erd.html
"""
import json
import re
import html
import argparse

from . import layout

HEADER_H = 34
ROW_H = 26
TABLE_W = 260
PADDING = 14


def box_dims(table):
    """Ancho/alto de una tabla sin depender de que ya tenga 'position'."""
    return (TABLE_W, HEADER_H + len(table["columns"]) * ROW_H)


SQL_KEYWORDS = [
    "CREATE TABLE", "PRIMARY KEY", "FOREIGN KEY", "REFERENCES", "NOT NULL",
    "DEFAULT", "UNIQUE", "UUID", "VARCHAR", "NUMERIC", "TIMESTAMP", "INT",
]


# ---------- geometría ----------

def table_box(table):
    x, y = table["position"]["x"], table["position"]["y"]
    h = HEADER_H + len(table["columns"]) * ROW_H
    return {"x": x, "y": y, "w": TABLE_W, "h": h}


def row_y(table, col_index):
    return table["position"]["y"] + HEADER_H + (col_index + 0.5) * ROW_H


def find_col_index(table, col_name):
    for i, c in enumerate(table["columns"]):
        if c["name"] == col_name:
            return i
    return None


def build_fk_edges(schema):
    tables_by_name = {t["name"]: t for t in schema["tables"]}
    edges = []
    for t in schema["tables"]:
        for col in t["columns"]:
            if "fk" in col:
                target = tables_by_name.get(col["fk"]["table"])
                if not target:
                    continue
                edges.append({
                    "id": f"fk-{len(edges)}",
                    "sourceTable": t["name"],
                    "sourceCol": col["name"],
                    "targetTable": target["name"],
                    "targetCol": col["fk"]["column"],
                })
    return edges


# ---------- SVG ----------

def render_table_svg(table):
    box = table_box(table)
    parts = [
        f'<g class="erd-table" data-table="{html.escape(table["name"])}">',
        f'<rect x="{box["x"]}" y="{box["y"]}" width="{box["w"]}" height="{box["h"]}" class="table-box"/>',
        f'<rect x="{box["x"]}" y="{box["y"]}" width="{box["w"]}" height="{HEADER_H}" class="table-header" data-header-for="{html.escape(table["name"])}"/>',
        f'<text x="{box["x"] + box["w"]/2}" y="{box["y"] + HEADER_H/2}" class="table-title" '
        f'text-anchor="middle" dominant-baseline="central" data-header-for="{html.escape(table["name"])}">'
        f'{html.escape(table["name"])}</text>',
    ]
    for i, col in enumerate(table["columns"]):
        ry = table["position"]["y"] + HEADER_H + i * ROW_H
        cy = ry + ROW_H / 2
        cls = "col-row" + (" col-row-alt" if i % 2 == 1 else "")
        marker = "\U0001F511 " if col.get("pk") else ("\U0001F517 " if "fk" in col else "")
        label = f'{marker}{col["name"]}'
        parts.append(
            f'<g class="col-row-group" data-table="{html.escape(table["name"])}" data-col="{html.escape(col["name"])}">'
            f'<rect x="{box["x"]}" y="{ry}" width="{box["w"]}" height="{ROW_H}" class="{cls}"/>'
            f'<text x="{box["x"] + 10}" y="{cy}" class="col-name" dominant-baseline="central">{html.escape(label)}</text>'
            f'<text x="{box["x"] + box["w"] - 10}" y="{cy}" class="col-type" text-anchor="end" '
            f'dominant-baseline="central">{html.escape(col["type"])}</text>'
            f'</g>'
        )
    parts.append("</g>")
    return "\n".join(parts)


def render_connector_svg(edge_id, source_table, source_col_idx, target_table, target_col_idx, canvas_w):
    s_box, t_box = table_box(source_table), table_box(target_table)
    sy, ty = row_y(source_table, source_col_idx), row_y(target_table, target_col_idx)
    dx = t_box["x"] - s_box["x"]

    if abs(dx) > 20:
        sx, tx = (s_box["x"] + s_box["w"], t_box["x"]) if dx > 0 else (s_box["x"], t_box["x"] + t_box["w"])
        midx = sx + (tx - sx) / 2
        path = f"M {sx},{sy} L {midx},{sy} L {midx},{ty} L {tx},{ty}"
    else:
        outer_left = s_box["x"] < canvas_w / 2
        sx = s_box["x"] if outer_left else s_box["x"] + s_box["w"]
        tx = t_box["x"] if outer_left else t_box["x"] + t_box["w"]
        bend_x = sx + (-40 if outer_left else 40)
        path = f"M {sx},{sy} L {bend_x},{sy} L {bend_x},{ty} L {tx},{ty}"

    return f'<path id="{edge_id}" d="{path}" class="fk-line" marker-end="url(#arrow)"/>'


def build_svg(schema, edges):
    tables_by_name = {t["name"]: t for t in schema["tables"]}
    boxes = [table_box(t) for t in schema["tables"]]
    canvas_w = max(b["x"] + b["w"] for b in boxes) + PADDING
    canvas_h = max(b["y"] + b["h"] for b in boxes) + PADDING

    parts = [
        f'<svg id="erd-svg" viewBox="0 0 {canvas_w} {canvas_h}" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">',
        "<defs><marker id=\"arrow\" markerWidth=\"10\" markerHeight=\"10\" refX=\"8\" refY=\"3\" "
        "orient=\"auto\" markerUnits=\"strokeWidth\"><path d=\"M0,0 L0,6 L9,3 z\" class=\"fk-arrow\"/></marker></defs>",
    ]
    for e in edges:
        source, target = tables_by_name[e["sourceTable"]], tables_by_name[e["targetTable"]]
        si, ti = find_col_index(source, e["sourceCol"]), find_col_index(target, e["targetCol"])
        if si is None or ti is None:
            continue
        parts.append(render_connector_svg(e["id"], source, si, target, ti, canvas_w))
    for t in schema["tables"]:
        parts.append(render_table_svg(t))
    parts.append("</svg>")
    return "\n".join(parts), canvas_w, canvas_h


def split_ddl_by_table(raw_ddl):
    blocks = {}
    for m in re.finditer(r"CREATE TABLE\s+(\w+)\s*\(.*?\);", raw_ddl, re.IGNORECASE | re.DOTALL):
        blocks[m.group(1)] = m.group(0)
    return blocks


def highlight_ddl(text):
    escaped = html.escape(text)
    for kw in sorted(SQL_KEYWORDS, key=len, reverse=True):
        escaped = re.sub(rf"\b{re.escape(kw)}\b", f'<span class="ddl-kw">{kw}</span>', escaped, flags=re.IGNORECASE)
    return escaped


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>ERD — {title}</title>
<style>
  :root {{
    --bg:#0f1117; --panel:#161922; --border:#2a2f3d; --header:#1f2436;
    --row-alt:#1a1e29; --text:#e6e8ef; --text-dim:#8b90a3;
    --accent:#5b8cff; --fk:#ffb454; --fk-active:#ffd27a; --pk:#67d68a; --selected:#28324a;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif; background:var(--bg); color:var(--text); display:flex; height:100vh; }}
  #diagram {{ flex:1 1 auto; overflow:hidden; position:relative; order:2; background:
      radial-gradient(circle, #1c2030 1px, transparent 1px) 0 0/22px 22px, var(--bg); }}
  #diagram svg {{ display:block; }}
  #sidebar {{ flex:0 0 460px; border-right:1px solid var(--border); background:var(--panel); display:flex; flex-direction:column; order:1; }}
  #query-panel {{ flex:0 0 auto; max-height:42%; display:flex; flex-direction:column; border-bottom:1px solid var(--border); padding:16px; }}
  #ddl-panel {{ flex:1 1 auto; overflow:auto; padding:16px; }}
  h2 {{ margin:0 0 8px 0; font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--text-dim); display:flex; justify-content:space-between; align-items:center; gap:8px; }}
  .h2-actions {{ display:flex; align-items:center; gap:6px; text-transform:none; letter-spacing:normal; }}
  .panel-btn {{ background:var(--header); border:1px solid var(--border); color:var(--text-dim); font-size:11px; padding:3px 8px; border-radius:4px; cursor:pointer; white-space:nowrap; }}
  .panel-btn:hover {{ color:var(--text); border-color:var(--accent); }}
  .panel-btn.primary {{ color:var(--accent); border-color:var(--accent); }}
  .mode-toggle {{ display:flex; align-items:center; gap:5px; font-size:11px; color:var(--text-dim); cursor:pointer; user-select:none; }}
  .mode-toggle input {{ accent-color: var(--accent); cursor:pointer; }}
  #query-mode-hint {{ font-size:11px; color:var(--text-dim); margin-bottom:8px; }}
  #query-text {{ flex:1 1 auto; width:100%; resize:none; background:#0c0e14; color:var(--text); border:1px solid var(--border); border-radius:6px; padding:10px; font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12.5px; line-height:1.5; }}
  #ddl-hint {{ font-size:11.5px; color:var(--text-dim); margin-bottom:10px; }}
  pre.ddl-block {{ font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12.5px; line-height:1.5; white-space:pre-wrap; word-break:break-word; margin:0 0 16px 0; padding:10px; background:#0c0e14; border:1px solid var(--border); border-radius:6px; }}
  .ddl-kw {{ color:var(--accent); font-weight:600; }}
  .table-box {{ fill:var(--panel); stroke:var(--border); stroke-width:1.5; rx:6; }}
  .table-header {{ fill:var(--header); rx:6; cursor:grab; }}
  .table-header:active {{ cursor:grabbing; }}
  .table-title {{ fill:var(--text); font-size:14px; font-weight:700; font-family:inherit; pointer-events:none; }}
  .col-row {{ fill:transparent; }}
  .col-row-alt {{ fill:var(--row-alt); }}
  .col-row-group {{ cursor:default; }}
  body.query-mode-active .col-row-group {{ cursor:pointer; }}
  .col-row-group[data-selected="true"] rect {{ fill:var(--selected); }}
  .col-name {{ fill:var(--text); font-size:12.5px; font-family:"SF Mono",Menlo,Consolas,monospace; }}
  .col-type {{ fill:var(--text-dim); font-size:11.5px; font-family:"SF Mono",Menlo,Consolas,monospace; }}
  .fk-line {{ fill:none; stroke:var(--fk); stroke-width:1.75; opacity:.7; transition:stroke .15s, stroke-width .15s, opacity .15s; }}
  .fk-line.active {{ stroke:var(--fk-active); stroke-width:3; opacity:1; }}
  .fk-arrow {{ fill:var(--fk); }}
  .erd-table.dimmed .table-box, .erd-table.dimmed .table-header {{ opacity:.25; }}
  .erd-table.dimmed .col-name, .erd-table.dimmed .col-type, .erd-table.dimmed .table-title {{ opacity:.25; }}
  .erd-table.focused .table-box {{ stroke:var(--accent); stroke-width:2.5; }}
  #zoom-controls {{ position:absolute; top:14px; right:14px; display:flex; flex-direction:column; gap:4px; z-index:5; }}
  #zoom-controls button {{ width:30px; height:30px; border-radius:6px; border:1px solid var(--border); background:var(--panel); color:var(--text); font-size:15px; cursor:pointer; }}
  #zoom-controls button:hover {{ border-color:var(--accent); color:var(--accent); }}
  #diagram-hint {{ position:absolute; bottom:10px; left:14px; font-size:11px; color:var(--text-dim); background:rgba(22,25,34,.8); padding:4px 8px; border-radius:4px; z-index:5; }}
</style>
</head>
<body>
  <div id="diagram">
    {svg}
    <div id="zoom-controls">
      <button id="zoom-in" title="Acercar">+</button>
      <button id="zoom-out" title="Alejar">–</button>
      <button id="zoom-reset" title="Restablecer vista">⤾</button>
    </div>
    <div id="diagram-hint">Arrastra el título de una tabla para moverla · scroll para zoom · arrastra el fondo para desplazar</div>
  </div>
  <div id="sidebar">
    <div id="query-panel">
      <h2>Borrador de query
        <span class="h2-actions">
          <label class="mode-toggle"><input type="checkbox" id="query-mode-toggle"> Modo selección</label>
          <button class="panel-btn" id="copy-query">Copiar</button>
          <button class="panel-btn" id="clear-query">Limpiar</button>
        </span>
      </h2>
      <div id="query-mode-hint">Activa "Modo selección" y click en columnas del diagrama para armar el JOIN.</div>
      <textarea id="query-text" readonly>-- Activa "Modo selección" y click en columnas del diagrama --</textarea>
    </div>
    <div id="ddl-panel">
      <h2><span id="ddl-title">DDL</span>
        <span class="h2-actions">
          <button class="panel-btn" id="show-related" style="display:none;">+ mostrar relacionadas</button>
          <button class="panel-btn" id="clear-focus" style="display:none;">Ver todo</button>
        </span>
      </h2>
      <div id="ddl-hint">Click en el header de una tabla para ver solo su DDL.</div>
      <div id="ddl-blocks">{ddl_blocks}</div>
    </div>
  </div>
<script>
const HEADER_H = {header_h};
const ROW_H = {row_h};
const CANVAS_W = {canvas_w};
const FK_EDGES = {fk_edges_json};
const TABLE_DIMS = {table_dims_json};      // nombre -> {{w,h}}
const TABLE_BOX = {table_pos_json};        // nombre -> {{x,y}}  (se muta al arrastrar)
const TABLE_ORIGIN = JSON.parse(JSON.stringify(TABLE_BOX)); // posiciones originales del SVG estático
const COLUMN_INDEX = {column_index_json}; // nombre -> {{col: idx}}

const svgRoot = document.getElementById('erd-svg');
const diagramEl = document.getElementById('diagram');

const lineByRow = {{}};
FK_EDGES.forEach(e => {{
  const srcKey = e.sourceTable + ':' + e.sourceCol;
  const tgtKey = e.targetTable + ':' + e.targetCol;
  (lineByRow[srcKey] ||= []).push(e.id);
  (lineByRow[tgtKey] ||= []).push(e.id);
}});

const adjacency = {{}};
FK_EDGES.forEach(e => {{
  (adjacency[e.sourceTable] ||= []).push({{other: e.targetTable, a: e.sourceCol, b: e.targetCol}});
  (adjacency[e.targetTable] ||= []).push({{other: e.sourceTable, a: e.targetCol, b: e.sourceCol}});
}});

function directRelated(tableName) {{
  const rel = new Set();
  FK_EDGES.forEach(e => {{
    if (e.sourceTable === tableName) rel.add(e.targetTable);
    if (e.targetTable === tableName) rel.add(e.sourceTable);
  }});
  return rel;
}}

// ================= hover: siempre activo =================
document.querySelectorAll('.col-row-group').forEach(g => {{
  const key = g.dataset.table + ':' + g.dataset.col;
  g.addEventListener('mouseenter', () => {{
    (lineByRow[key] || []).forEach(id => document.getElementById(id).classList.add('active'));
  }});
  g.addEventListener('mouseleave', () => {{
    (lineByRow[key] || []).forEach(id => document.getElementById(id).classList.remove('active'));
  }});
}});

// ================= foco de DDL =================
let focusedTable = null;
let showRelated = false;

function refreshFocusDisplay() {{
  const visible = focusedTable
    ? new Set([focusedTable, ...(showRelated ? directRelated(focusedTable) : [])])
    : null;

  document.querySelectorAll('.erd-table').forEach(t => {{
    const name = t.dataset.table;
    const show = !visible || visible.has(name);
    t.classList.toggle('dimmed', !!visible && !show);
    t.classList.toggle('focused', name === focusedTable);
  }});
  document.querySelectorAll('.ddl-block').forEach(b => {{
    const show = !visible || visible.has(b.dataset.table);
    b.style.display = show ? 'block' : 'none';
  }});

  document.getElementById('ddl-title').textContent = focusedTable ? ('DDL — ' + focusedTable) : 'DDL';
  document.getElementById('clear-focus').style.display = focusedTable ? 'inline-block' : 'none';
  const relBtn = document.getElementById('show-related');
  relBtn.style.display = focusedTable ? 'inline-block' : 'none';
  relBtn.textContent = showRelated ? '- ocultar relacionadas' : '+ mostrar relacionadas';
}}

document.getElementById('show-related').addEventListener('click', () => {{
  showRelated = !showRelated;
  refreshFocusDisplay();
}});
document.getElementById('clear-focus').addEventListener('click', () => {{
  focusedTable = null;
  showRelated = false;
  refreshFocusDisplay();
}});

// ================= pan & zoom (viewBox) =================
let viewBox = {{ x: 0, y: 0, w: CANVAS_W_VB, h: CANVAS_H_VB }};
function updateViewBox() {{
  svgRoot.setAttribute('viewBox', `${{viewBox.x}} ${{viewBox.y}} ${{viewBox.w}} ${{viewBox.h}}`);
}}
function svgPoint(evt) {{
  const pt = svgRoot.createSVGPoint();
  pt.x = evt.clientX; pt.y = evt.clientY;
  return pt.matrixTransform(svgRoot.getScreenCTM().inverse());
}}
function zoomBy(factor, cx, cy) {{
  if (cx === undefined) {{ cx = viewBox.x + viewBox.w / 2; cy = viewBox.y + viewBox.h / 2; }}
  const newW = Math.max(200, Math.min(viewBox.w * factor, CANVAS_W_VB * 6));
  const newH = newW * (viewBox.h / viewBox.w);
  viewBox.x = cx - (cx - viewBox.x) * (newW / viewBox.w);
  viewBox.y = cy - (cy - viewBox.y) * (newH / viewBox.h);
  viewBox.w = newW; viewBox.h = newH;
  updateViewBox();
}}
diagramEl.addEventListener('wheel', (e) => {{
  e.preventDefault();
  const p = svgPoint(e);
  zoomBy(e.deltaY < 0 ? 0.9 : 1.1, p.x, p.y);
}}, {{ passive: false }});
document.getElementById('zoom-in').addEventListener('click', () => zoomBy(0.85));
document.getElementById('zoom-out').addEventListener('click', () => zoomBy(1.18));
document.getElementById('zoom-reset').addEventListener('click', () => {{
  viewBox = {{ x: 0, y: 0, w: CANVAS_W_VB, h: CANVAS_H_VB }};
  updateViewBox();
}});

let panState = null;
svgRoot.addEventListener('mousedown', (e) => {{
  if (e.target.closest('.table-header') || e.target.closest('.col-row-group')) return;
  panState = {{ startX: e.clientX, startY: e.clientY, vb0: {{ ...viewBox }} }};
}});

// ================= mover tablas (arrastrar header) =================
let dragState = null;

function rowY(tableName, colName) {{
  const idx = COLUMN_INDEX[tableName][colName];
  return TABLE_BOX[tableName].y + HEADER_H + (idx + 0.5) * ROW_H;
}}

function computeEdgePath(edge) {{
  const sBox = TABLE_BOX[edge.sourceTable], tBox = TABLE_BOX[edge.targetTable];
  const sDim = TABLE_DIMS[edge.sourceTable], tDim = TABLE_DIMS[edge.targetTable];
  const sy = rowY(edge.sourceTable, edge.sourceCol);
  const ty = rowY(edge.targetTable, edge.targetCol);
  const dx = tBox.x - sBox.x;
  if (Math.abs(dx) > 20) {{
    let sx, tx;
    if (dx > 0) {{ sx = sBox.x + sDim.w; tx = tBox.x; }}
    else {{ sx = sBox.x; tx = tBox.x + tDim.w; }}
    const midx = sx + (tx - sx) / 2;
    return `M ${{sx}},${{sy}} L ${{midx}},${{sy}} L ${{midx}},${{ty}} L ${{tx}},${{ty}}`;
  }} else {{
    const outerLeft = sBox.x < CANVAS_W / 2;
    const sx = outerLeft ? sBox.x : sBox.x + sDim.w;
    const tx = outerLeft ? tBox.x : tBox.x + tDim.w;
    const bendX = sx + (outerLeft ? -40 : 40);
    return `M ${{sx}},${{sy}} L ${{bendX}},${{sy}} L ${{bendX}},${{ty}} L ${{tx}},${{ty}}`;
  }}
}}

function moveTable(name, x, y) {{
  TABLE_BOX[name].x = x;
  TABLE_BOX[name].y = y;
  const g = document.querySelector('.erd-table[data-table="' + CSS.escape(name) + '"]');
  const dx = x - TABLE_ORIGIN[name].x, dy = y - TABLE_ORIGIN[name].y;
  g.setAttribute('transform', `translate(${{dx}}, ${{dy}})`);
  FK_EDGES.forEach(edge => {{
    if (edge.sourceTable === name || edge.targetTable === name) {{
      document.getElementById(edge.id).setAttribute('d', computeEdgePath(edge));
    }}
  }});
}}

document.querySelectorAll('.table-header').forEach(header => {{
  header.addEventListener('mousedown', (e) => {{
    e.preventDefault();
    e.stopPropagation();
    const name = header.dataset.headerFor;
    const p = svgPoint(e);
    dragState = {{ name, startX: p.x, startY: p.y, origX: TABLE_BOX[name].x, origY: TABLE_BOX[name].y, moved: false }};
  }});
}});

window.addEventListener('mousemove', (e) => {{
  if (dragState) {{
    const p = svgPoint(e);
    const dx = p.x - dragState.startX, dy = p.y - dragState.startY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragState.moved = true;
    if (dragState.moved) moveTable(dragState.name, dragState.origX + dx, dragState.origY + dy);
    return;
  }}
  if (panState) {{
    const rect = svgRoot.getBoundingClientRect();
    const scale = viewBox.w / rect.width;
    viewBox.x = panState.vb0.x - (e.clientX - panState.startX) * scale;
    viewBox.y = panState.vb0.y - (e.clientY - panState.startY) * scale;
    updateViewBox();
  }}
}});

window.addEventListener('mouseup', () => {{
  if (dragState) {{
    if (!dragState.moved) {{
      // fue un click, no un arrastre -> togglear foco de DDL
      const name = dragState.name;
      focusedTable = (focusedTable === name) ? null : name;
      showRelated = false;
      refreshFocusDisplay();
    }}
    dragState = null;
  }}
  panState = null;
}});

// ================= modo selección / query builder =================
let queryMode = false;
document.getElementById('query-mode-toggle').addEventListener('change', (e) => {{
  queryMode = e.target.checked;
  document.body.classList.toggle('query-mode-active', queryMode);
  document.getElementById('query-mode-hint').style.display = queryMode ? 'none' : 'block';
}});

let selectedColumns = [];

function bfsPath(startTables, target) {{
  const visited = new Set(startTables);
  const queue = startTables.map(t => ({{ table: t, path: [] }}));
  while (queue.length) {{
    const {{ table, path }} = queue.shift();
    if (table === target) return path;
    (adjacency[table] || []).forEach(edge => {{
      if (!visited.has(edge.other)) {{
        visited.add(edge.other);
        queue.push({{ table: edge.other, path: [...path, {{ from: table, to: edge.other, a: edge.a, b: edge.b }}] }});
      }}
    }});
  }}
  return null;
}}

function regenerateQuery() {{
  const box = document.getElementById('query-text');
  if (selectedColumns.length === 0) {{
    box.value = '-- Activa "Modo selección" y click en columnas del diagrama --';
    return;
  }}
  const tableOrder = [];
  selectedColumns.forEach(c => {{ if (!tableOrder.includes(c.table)) tableOrder.push(c.table); }});

  let joined = [tableOrder[0]];
  const joinClauses = [];
  for (const t of tableOrder.slice(1)) {{
    if (joined.includes(t)) continue;
    const path = bfsPath(joined, t);
    if (!path) {{
      joinClauses.push(`-- no se encontró relación FK entre las tablas seleccionadas y "${{t}}"`);
      continue;
    }}
    path.forEach(step => {{
      if (!joined.includes(step.to)) {{
        joinClauses.push(`JOIN ${{step.to}} ON ${{step.from}}.${{step.a}} = ${{step.to}}.${{step.b}}`);
        joined.push(step.to);
      }}
    }});
  }}

  const cols = selectedColumns.map(c => `${{c.table}}.${{c.col}}`);
  let sql = `SELECT\\n  ${{cols.join(',\\n  ')}}\\nFROM ${{tableOrder[0]}}`;
  if (joinClauses.length) sql += '\\n' + joinClauses.join('\\n');
  sql += ';';
  box.value = sql;
}}

document.querySelectorAll('.col-row-group').forEach(g => {{
  g.addEventListener('click', () => {{
    if (!queryMode) return;
    const table = g.dataset.table, col = g.dataset.col;
    const idx = selectedColumns.findIndex(c => c.table === table && c.col === col);
    if (idx >= 0) {{
      selectedColumns.splice(idx, 1);
      g.removeAttribute('data-selected');
    }} else {{
      selectedColumns.push({{ table, col }});
      g.setAttribute('data-selected', 'true');
    }}
    regenerateQuery();
  }});
}});

document.getElementById('clear-query').addEventListener('click', () => {{
  selectedColumns = [];
  document.querySelectorAll('.col-row-group[data-selected]').forEach(g => g.removeAttribute('data-selected'));
  regenerateQuery();
}});

document.getElementById('copy-query').addEventListener('click', async () => {{
  const box = document.getElementById('query-text');
  try {{ await navigator.clipboard.writeText(box.value); }}
  catch (err) {{ box.select(); document.execCommand('copy'); }}
  const btn = document.getElementById('copy-query');
  const original = btn.textContent;
  btn.textContent = 'Copiado ✓';
  btn.classList.add('primary');
  setTimeout(() => {{ btn.textContent = original; btn.classList.remove('primary'); }}, 1400);
}});
</script>
</body>
</html>
"""


def render_schema_to_html(schema, title="schema"):
    """
    schema: dict con el formato intermedio (ver references/schema_format.md).
    Devuelve el HTML final como string. Muta schema['tables'][*]['position']
    in-place si faltaban (efecto secundario del auto-layout, documentado).
    """
    edges = build_fk_edges(schema)

    if any("position" not in t for t in schema["tables"]):
        names = [t["name"] for t in schema["tables"]]
        dims = {t["name"]: box_dims(t) for t in schema["tables"]}
        edge_pairs = list({(e["sourceTable"], e["targetTable"]) for e in edges})
        positions = layout.compute_auto_layout(names, edge_pairs, dims)
        for t in schema["tables"]:
            t["position"] = positions[t["name"]]

    svg, canvas_w, canvas_h = build_svg(schema, edges)

    raw_ddl = schema.get("raw_ddl", "")
    ddl_by_table = split_ddl_by_table(raw_ddl)
    ddl_blocks_html = "\n".join(
        f'<pre class="ddl-block" data-table="{html.escape(name)}">{highlight_ddl(block)}</pre>'
        for name, block in ddl_by_table.items()
    )

    table_dims = {t["name"]: {"w": box_dims(t)[0], "h": box_dims(t)[1]} for t in schema["tables"]}
    table_pos = {t["name"]: {"x": t["position"]["x"], "y": t["position"]["y"]} for t in schema["tables"]}
    column_index = {t["name"]: {c["name"]: i for i, c in enumerate(t["columns"])} for t in schema["tables"]}

    out = HTML_TEMPLATE.format(
        title=title,
        svg=svg,
        ddl_blocks=ddl_blocks_html,
        header_h=HEADER_H,
        row_h=ROW_H,
        canvas_w=canvas_w,
        fk_edges_json=json.dumps(edges),
        table_dims_json=json.dumps(table_dims),
        table_pos_json=json.dumps(table_pos),
        column_index_json=json.dumps(column_index),
    )
    # los dos placeholders de tamaño inicial del viewBox se resuelven aparte
    # (van dentro del bloque <script>, con nombres que no chocan con .format)
    out = out.replace("CANVAS_W_VB", str(canvas_w)).replace("CANVAS_H_VB", str(canvas_h))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("schema_json")
    ap.add_argument("-o", "--output", default="erd.html")
    args = ap.parse_args()

    with open(args.schema_json) as f:
        schema = json.load(f)

    out = render_schema_to_html(schema, title=args.schema_json)

    with open(args.output, "w") as f:
        f.write(out)
    print(f"Escrito {args.output}")


if __name__ == "__main__":
    main()
