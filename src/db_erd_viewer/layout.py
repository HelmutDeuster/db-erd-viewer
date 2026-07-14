"""
layout.py

Auto-layout de tablas para el ERD cuando el JSON no trae posiciones manuales.

Estrategia en dos pasos:
  1. Layout tipo fuerza dirigida (spring model) usando los FKs como aristas de
     atracción, para que tablas relacionadas queden cerca entre sí.
  2. Resolución de solapes: empuja cajas que se pisan hasta que no haya overlap,
     respetando el tamaño real de cada tabla (ancho fijo, alto según # columnas).

Sin dependencias externas (pure Python) a propósito, para que instalar la skill
no requiera numpy/networkx.
"""
import math
import random


def compute_auto_layout(names, edges, box_dims, canvas_w=1800, canvas_h=1400,
                         iterations=400, padding=40, seed=7):
    """
    names: lista de nombres de tabla
    edges: lista de tuplas (tabla_a, tabla_b) — una por cada relación FK
    box_dims: dict tabla -> (width, height)
    Devuelve dict tabla -> {"x": ..., "y": ...}
    """
    if not names:
        return {}
    random.seed(seed)
    pos = {n: [random.uniform(0, canvas_w), random.uniform(0, canvas_h)] for n in names}
    k = math.sqrt((canvas_w * canvas_h) / len(names))

    for it in range(iterations):
        disp = {n: [0.0, 0.0] for n in names}

        # repulsión entre todos los pares (evita amontonamiento)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                dist = math.hypot(dx, dy) or 0.01
                force = (k * k) / dist
                fx, fy = dx / dist * force, dy / dist * force
                disp[a][0] += fx
                disp[a][1] += fy
                disp[b][0] -= fx
                disp[b][1] -= fy

        # atracción por cada FK (acerca tablas relacionadas)
        for a, b in edges:
            if a not in pos or b not in pos:
                continue
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            dist = math.hypot(dx, dy) or 0.01
            force = (dist * dist) / k
            fx, fy = dx / dist * force, dy / dist * force
            disp[a][0] -= fx
            disp[a][1] -= fy
            disp[b][0] += fx
            disp[b][1] += fy

        # enfriamiento: los movimientos se hacen mas chicos con cada iteracion
        temp = canvas_w * 0.1 * (1 - it / iterations)
        for n in names:
            dx, dy = disp[n]
            dist = math.hypot(dx, dy) or 0.01
            capped = min(dist, max(temp, 0.01))
            pos[n][0] += dx / dist * capped
            pos[n][1] += dy / dist * capped

    layout = {
        n: {"x": pos[n][0] - box_dims[n][0] / 2, "y": pos[n][1] - box_dims[n][1] / 2,
            "w": box_dims[n][0], "h": box_dims[n][1]}
        for n in names
    }
    layout = _resolve_overlaps(layout, padding=padding)

    min_x = min(b["x"] for b in layout.values())
    min_y = min(b["y"] for b in layout.values())
    for n in layout:
        layout[n]["x"] -= (min_x - padding)
        layout[n]["y"] -= (min_y - padding)

    return {n: {"x": round(layout[n]["x"], 1), "y": round(layout[n]["y"], 1)} for n in names}


def _resolve_overlaps(layout, padding=40, iterations=300):
    """Empuja cajas que se solapan hasta separarlas, respetando su tamaño real."""
    names = list(layout.keys())
    for _ in range(iterations):
        moved = False
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ba, bb = layout[a], layout[b]
                ax1, ay1 = ba["x"] - padding / 2, ba["y"] - padding / 2
                ax2, ay2 = ba["x"] + ba["w"] + padding / 2, ba["y"] + ba["h"] + padding / 2
                bx1, by1 = bb["x"] - padding / 2, bb["y"] - padding / 2
                bx2, by2 = bb["x"] + bb["w"] + padding / 2, bb["y"] + bb["h"] + padding / 2

                overlap_x = min(ax2, bx2) - max(ax1, bx1)
                overlap_y = min(ay2, by2) - max(ay1, by1)
                if overlap_x > 0 and overlap_y > 0:
                    moved = True
                    acx, acy = ba["x"] + ba["w"] / 2, ba["y"] + ba["h"] / 2
                    bcx, bcy = bb["x"] + bb["w"] / 2, bb["y"] + bb["h"] / 2
                    if overlap_x < overlap_y:
                        shift = overlap_x / 2 + 1
                        if acx < bcx:
                            ba["x"] -= shift
                            bb["x"] += shift
                        else:
                            ba["x"] += shift
                            bb["x"] -= shift
                    else:
                        shift = overlap_y / 2 + 1
                        if acy < bcy:
                            ba["y"] -= shift
                            bb["y"] += shift
                        else:
                            ba["y"] += shift
                            bb["y"] -= shift
        if not moved:
            break
    return layout
