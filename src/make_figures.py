"""Stage 7 - network visualisations.

Writes a self-contained interactive page plus standalone SVGs:

    figures/interlock_network.html   all three figures, hover + table view
    figures/fig1_core_interlocks.svg core interlock network
    figures/fig2_by_period.svg       small multiples, one panel per period
    figures/fig3_ego_indochine.svg   one firm's interlock neighbourhood

Design decisions that follow from the data's job, not from taste:

- **The full interlock graph is a hairball** (3,085 nodes, 39,523 edges at
  weight >= 1) and is never drawn whole. Figure 1 draws the core: firms sharing
  at least two directors, largest component, top N by weighted degree.
- **A node-link diagram is an all-pairs form** - any two node colours can end
  up adjacent - so the categorical cap is three slots plus "Other", not the
  eight a bar chart could carry. Territories are folded to the top three.
- **Colour carries identity (territory); size carries magnitude (degree).**
  Two encodings, two jobs, no rainbow ramp standing in for a quantity.
- Light-mode aqua sits below 3:1 on the surface, so the palette's relief rule
  applies: direct labels on the largest nodes and a full table view ship with
  the figure rather than being optional.

Layouts are computed with a fixed seed so the figures are reproducible.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_network import PERIODS, read_csv  # noqa: E402
from common import ensure_dir  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG_DIR = os.path.join(ROOT, "figures")

# Width reserved either side of a node-link panel for stacked labels.
LABEL_MARGIN = 272.0
CORE_W, CORE_H = 1340.0, 780.0
EGO_W, EGO_H = 1340.0, 660.0

# Categorical slots 1-3 from the validated palette. Three is the all-pairs cap;
# everything else is the recessive "Other" grey, which is not a slot.
PALETTE = {
    "light": {
        "surface": "#fcfcfb",
        "text_primary": "#0b0b0b",
        "text_secondary": "#52514e",
        "text_muted": "#8a8983",
        "hairline": "#e6e5e1",
        "series": ["#2a78d6", "#eb6834", "#1baf7a"],
        "other": "#a9a8a2",
        "edge": "#c9c8c2",
    },
    "dark": {
        "surface": "#1a1a19",
        "text_primary": "#ffffff",
        "text_secondary": "#c3c2b7",
        "text_muted": "#8a8983",
        "hairline": "#33332f",
        "series": ["#3987e5", "#d95926", "#199e70"],
        "other": "#6f6e69",
        "edge": "#3d3d39",
    },
}

# A third "mode" that emits CSS custom properties instead of literal colours,
# so one SVG serves both themes. Inside an HTML page that defines the
# variables this halves the markup: the light and dark renderings of a figure
# differ only in colour, and inlining both put 7 MB of duplicate geometry into
# the territory gallery. Standalone SVG files still use the literal modes -
# there is no page to define the variables.
PALETTE["vars"] = {
    "surface": "var(--surface)",
    "text_primary": "var(--text-primary)",
    "text_secondary": "var(--text-secondary)",
    "text_muted": "var(--text-muted)",
    "hairline": "var(--hairline)",
    "series": ["var(--s1)", "var(--s2)", "var(--s3)"],
    "other": "var(--other)",
    "edge": "var(--edge)",
}


# --- graph construction --------------------------------------------------
def build_interlock_graph(min_weight: int):
    import networkx as nx

    G = nx.Graph()
    for e in read_csv("edges_company_interlock.csv"):
        w = int(e["weight"])
        if w >= min_weight:
            G.add_edge(e["company_id_1"], e["company_id_2"], weight=w)
    return G


def core_subgraph(G, top_n: int):
    """Largest component, then the top_n nodes by weighted degree."""
    import networkx as nx

    if G.number_of_nodes() == 0:
        return G
    largest = max(nx.connected_components(G), key=len)
    H = G.subgraph(largest).copy()
    wdeg = dict(H.degree(weight="weight"))
    keep = sorted(wdeg, key=lambda n: -wdeg[n])[:top_n]
    K = H.subgraph(keep).copy()
    # Drop nodes that lost all their neighbours in the cut.
    K.remove_nodes_from([n for n, d in K.degree() if d == 0])
    return K


def layout(G, seed: int = 7, iterations: int = 260):
    import networkx as nx

    if G.number_of_nodes() == 0:
        return {}
    k = 1.6 / math.sqrt(G.number_of_nodes())
    return nx.spring_layout(G, k=k, iterations=iterations, seed=seed, weight="weight")


def normalise(pos: dict, width: float, height: float, pad: float,
              pad_x: float | None = None, robust: float = 0.0) -> dict:
    """Fit a layout into the canvas. `pad_x` reserves side margins for labels.

    `robust` fits to a central percentile range instead of the extremes and
    clamps the rest into the box. A spring layout usually throws one or two
    nodes far out; scaling to the true min/max then squashes every other node
    into a dot, which is what happened to the period panels.
    """
    if not pos:
        return {}
    xs = sorted(p[0] for p in pos.values())
    ys = sorted(p[1] for p in pos.values())

    def span(vals):
        if robust <= 0 or len(vals) < 12:
            return vals[0], vals[-1]
        i = int(len(vals) * robust)
        return vals[i], vals[-1 - i]

    x0, x1 = span(xs)
    y0, y1 = span(ys)
    px = pad if pad_x is None else pad_x
    sx = (width - 2 * px) / (x1 - x0) if x1 > x0 else 1
    sy = (height - 2 * pad) / (y1 - y0) if y1 > y0 else 1
    s = min(sx, sy)
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    out = {}
    for n, p in pos.items():
        x = width / 2 + (p[0] - cx) * s
        y = height / 2 - (p[1] - cy) * s
        out[n] = (min(max(x, px * 0.35), width - px * 0.35),
                  min(max(y, pad * 0.35), height - pad * 0.35))
    return out


# --- SVG ------------------------------------------------------------------
def esc(t: str) -> str:
    return html.escape(str(t), quote=True)


def radius(weighted_degree: float, lo: float, hi: float) -> float:
    """Area-proportional radius, so a node twice the degree looks twice as big."""
    if hi <= lo:
        return 5.0
    t = (weighted_degree - lo) / (hi - lo)
    return 3.2 + 11.0 * math.sqrt(max(t, 0.0))


def draw_network(nodes, edges, width, height, mode, label_top=0, font=11.0,
                 label_margin=0.0, edge_opacity=1.0, node_ring=2.0):
    """Return SVG body for one node-link panel. `nodes` carries x, y, r, color.

    `edge_opacity` scales the edge ink and `node_ring` the surface ring around
    each node. Both exist for the whole-graph figure: at 39,523 edges and
    3,085 nodes the defaults tuned for a 170-node core fill the canvas solid,
    and the shape of the graph — the thing that figure is for — disappears.
    """
    p = PALETTE[mode]
    out = []
    # Edges first, hairline and recessive, opacity scaled by shared directors.
    # Batched into one path per (width, opacity) bucket rather than one <line>
    # each: at 39,523 edges the per-element markup was 5 MB of the empire
    # figure alone, and the rendering is identical.
    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for a, b, w in edges:
        op = min(0.16 + 0.12 * (w - 1), 0.62) * edge_opacity
        sw = min(0.6 + 0.28 * (w - 1), 2.0) * min(1.0, edge_opacity * 2)
        buckets[(f"{sw:.2f}", f"{op:.3f}")].append(
            f"M{a[0]:.1f} {a[1]:.1f}L{b[0]:.1f} {b[1]:.1f}")
    out.append(f'<g stroke="{p["edge"]}" fill="none">')
    for (sw, op), segs in buckets.items():
        out.append(f'<path d="{"".join(segs)}" stroke-width="{sw}" '
                   f'stroke-opacity="{op}"/>')
    out.append("</g>")
    # Nodes, each with a surface ring so overlaps stay readable.
    out.append("<g>")
    for n in nodes:
        out.append(
            f'<circle class="nd" data-id="{esc(n["id"])}" cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" '
            f'r="{n["r"]:.2f}" fill="{n["color"]}" stroke="{p["surface"]}" '
            f'stroke-width="{node_ring:g}"/>'
        )
    out.append("</g>")
    # Selective direct labels. In a core this dense there is no free space
    # beside a node, so labels live in the side margins with hairline leaders -
    # the standard solution, and the relief the palette's contrast WARN
    # requires. Collision is impossible by construction: each side is a
    # vertically stacked column.
    if label_top:
        for lx, ly, anchor, text, nx_, ny_ in _margin_labels(
            nodes, label_top, font, width, height, label_margin
        ):
            out.append(
                f'<line x1="{lx + (4 if anchor == "start" else -4):.1f}" y1="{ly - font * 0.32:.1f}" '
                f'x2="{nx_:.1f}" y2="{ny_:.1f}" stroke="{p["text_muted"]}" '
                f'stroke-width="0.6" stroke-opacity="0.55"/>'
            )
        out.append(
            f'<g font-size="{font}" font-family="ui-sans-serif,system-ui,sans-serif" '
            f'fill="{p["text_primary"]}">'
        )
        for lx, ly, anchor, text, nx_, ny_ in _margin_labels(
            nodes, label_top, font, width, height, label_margin
        ):
            out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">{esc(text)}</text>')
        out.append("</g>")
    return "\n".join(out)


# Calibrated against Chromium's getComputedTextLength for the label strings
# actually used here: the raw formula ran 13-21% low, so it is scaled by a
# factor above the worst observed case. Under-estimating clips the label.
_WIDTH_SAFETY = 1.25


def _text_width(text: str, font: float) -> float:
    """Conservative estimate of rendered width for a sans-serif string."""
    narrow = sum(1 for c in text if c in "iljtIf.,'\u2019 ()")
    wide = sum(1 for c in text if c.isupper() or c in "mwMW")
    raw = font * (0.5 * len(text) - 0.22 * narrow + 0.12 * wide)
    return raw * _WIDTH_SAFETY


def trim_to_width(text: str, font: float, avail: float, floor: int = 10) -> str:
    """Shorten `text` until it fits `avail` px, ellipsising if anything went.

    The ellipsis is measured inside the loop, not bolted on after it. Adding it
    afterwards is the obvious version and it is wrong: the returned string is
    then wider than the space it was fitted to, which put every trimmed
    territory label a few pixels past the canvas edge.
    """
    if _text_width(text, font) <= avail:
        return text
    out = text
    while len(out) > floor and _text_width(_ellipsise(out), font) > avail:
        out = out[:-2]
    return _ellipsise(out)


def _ellipsise(text: str) -> str:
    return text.rstrip(" ,-’'(") + "…"


def _margin_labels(nodes, label_top, font, width, height, margin):
    """Stack labels down the left and right margins with leader lines."""
    ranked = sorted(nodes, key=lambda n: -n["r"])[:label_top]
    mid = width / 2
    sides = {"left": [], "right": []}
    for n in ranked:
        sides["left" if n["x"] < mid else "right"].append(n)
    # Balance the columns. Degree and horizontal position are correlated here,
    # so an unbalanced split leaves one margin empty and crams the other; move
    # the nodes nearest the centre line across until the split is even.
    for a, b in (("left", "right"), ("right", "left")):
        while len(sides[a]) - len(sides[b]) > 1:
            movers = sorted(sides[a], key=lambda n: -abs(n["x"] - mid))
            sides[a].remove(movers[-1])
            sides[b].append(movers[-1])

    step = font * 1.62
    out = []
    for side, items in sides.items():
        items.sort(key=lambda n: n["y"])
        top = max(font * 1.4, (height - step * (len(items) - 1)) / 2)
        top = min(top, height - step * (len(items) - 1) - font * 0.6)
        for i, n in enumerate(items):
            ly = top + i * step
            if side == "left":
                lx, anchor = margin - 14, "end"
                edge_x = n["x"] - n["r"] - 1
            else:
                lx, anchor = width - margin + 14, "start"
                edge_x = n["x"] + n["r"] + 1
            # Trim to the space actually available between the label anchor
            # and the canvas edge, so nothing is clipped.
            avail = (lx - 6) if side == "left" else (width - lx - 6)
            out.append((lx, ly, anchor, trim_to_width(n["label"], font, avail),
                        edge_x, n["y"]))
    return out


LEGEND_H = 38.0


def legend_svg(items, width: float, y: float, mode: str, font: float = 12.5) -> str:
    """A swatch-and-label row. Standalone SVGs leave the page's HTML legend
    behind, so without this one identity would rest on colour alone."""
    p = PALETTE[mode]
    out = [f'<g font-size="{font}" font-family="ui-sans-serif,system-ui,sans-serif" '
           f'fill="{p["text_secondary"]}">']
    x = 0.0
    for colour, label in items:
        out.append(
            f'<circle cx="{x + 5:.1f}" cy="{y - font * 0.34:.1f}" r="5" fill="{colour}"/>'
            f'<text x="{x + 16:.1f}" y="{y:.1f}">{esc(label)}</text>'
        )
        x += 16 + _text_width(label, font) + 26
    out.append("</g>")
    return "".join(out)


CAPTION_FONT = 11.5
CAPTION_LEAD = 15.0


def wrap_to_width(text: str, font: float, avail: float) -> list[str]:
    """Greedy word wrap. SVG has no flow text, so a caption longer than the
    canvas is simply clipped unless it is broken into lines here."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and _text_width(trial, font) > avail:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def svg_document(body: str, width: float, height: float, mode: str, title: str,
                 legend=None, caption: str = "") -> str:
    p = PALETTE[mode]
    lines = wrap_to_width(caption, CAPTION_FONT, width - 8) if caption else []
    extra = (LEGEND_H if legend else 0.0) + (len(lines) * CAPTION_LEAD + 8 if lines else 0.0)
    total = height + extra
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {total:.0f}" '
        f'width="{width:.0f}" height="{total:.0f}" role="img" aria-label="{esc(title)}">',
        f'<title>{esc(title)}</title>',
        f'<rect width="{width:.0f}" height="{total:.0f}" fill="{p["surface"]}"/>',
        body,
    ]
    if legend:
        parts.append(legend_svg(legend, width, height + 22, mode))
    if lines:
        y0 = height + (LEGEND_H if legend else 0.0) + CAPTION_FONT + 4
        parts.append(
            f'<g font-size="{CAPTION_FONT}" '
            f'font-family="ui-sans-serif,system-ui,sans-serif" fill="{p["text_muted"]}">'
            + "".join(f'<text x="0" y="{y0 + i * CAPTION_LEAD:.1f}">{esc(ln)}</text>'
                      for i, ln in enumerate(lines))
            + "</g>"
        )
    parts.append("</svg>")
    return "".join(parts)


# --- figure builders ------------------------------------------------------
def territory_of(rec: dict) -> str:
    return (rec.get("countries") or rec.get("regions") or "").split("; ")[0] or "(unlabelled)"


def prepare_core(companies, top_n, min_weight, width, height):
    G = build_interlock_graph(min_weight)
    K = core_subgraph(G, top_n)
    pos = normalise(layout(K), width, height, pad=44, pad_x=LABEL_MARGIN)

    terr_counts = Counter(territory_of(companies.get(n, {})) for n in K.nodes())
    top3 = [t for t, _ in terr_counts.most_common(3)]
    colour_of = {t: i for i, t in enumerate(top3)}

    wdeg = dict(K.degree(weight="weight"))
    lo, hi = (min(wdeg.values()), max(wdeg.values())) if wdeg else (0, 1)

    nodes = []
    for n in K.nodes():
        rec = companies.get(n, {})
        t = territory_of(rec)
        nodes.append({
            "id": n,
            "label": (rec.get("name") or n),
            "territory": t,
            "slot": colour_of.get(t, -1),
            "wdeg": wdeg[n],
            "degree": K.degree(n),
            "n_directors": rec.get("n_directors", ""),
            "sectors": (rec.get("sectors") or "").split("; ")[0][:40],
            "years": f"{rec.get('first_year_observed','')}-{rec.get('last_year_observed','')}",
            "x": pos[n][0], "y": pos[n][1],
            "r": radius(wdeg[n], lo, hi),
        })
    edges = [(pos[a], pos[b], d["weight"]) for a, b, d in K.edges(data=True)]
    return nodes, edges, top3, K


def colourise(nodes, mode):
    p = PALETTE[mode]
    for n in nodes:
        n["color"] = p["series"][n["slot"]] if n["slot"] >= 0 else p["other"]
    return nodes


def build_period_panels(companies, min_weight, top_n, w, h):
    """One small-multiple panel per period, on a SHARED layout.

    Each panel must be comparable to its neighbours, so the layout is computed
    once on the union of all periods and every panel draws its own subgraph at
    those fixed coordinates. Normalising each panel independently - the obvious
    implementation - rescales every panel to fill its box, which made the
    1914-29 panel (1,764 interlocks) look smaller than pre-1914 (299): the
    visual encoding then contradicts the data it is supposed to show.
    """
    import networkx as nx

    rows = read_csv("edges_company_interlock_by_period.csv")
    by_period = defaultdict(list)
    for e in rows:
        if int(e["weight"]) >= min_weight:
            by_period[e["period"]].append(e)

    union = nx.Graph()
    for es in by_period.values():
        for e in es:
            a, b = e["company_id_1"], e["company_id_2"]
            wgt = int(e["weight"])
            if union.has_edge(a, b):
                union[a][b]["weight"] = max(union[a][b]["weight"], wgt)
            else:
                union.add_edge(a, b, weight=wgt)
    if union.number_of_nodes() == 0:
        return []
    U = core_subgraph(union, top_n)
    pos = normalise(layout(U, seed=13, iterations=220), w, h, pad=16, robust=0.03)
    # One size scale for every panel, from the union degrees.
    wdeg_all = dict(U.degree(weight="weight"))
    lo, hi = min(wdeg_all.values()), max(wdeg_all.values())

    panels = []
    for name, _, _ in PERIODS:
        es = [e for e in by_period.get(name, [])
              if e["company_id_1"] in pos and e["company_id_2"] in pos]
        present = {e["company_id_1"] for e in es} | {e["company_id_2"] for e in es}
        nodes = [{
            "id": n,
            "label": companies.get(n, {}).get("name") or n,
            "x": pos[n][0], "y": pos[n][1],
            "r": max(2.0, radius(wdeg_all[n], lo, hi) * 0.5),
            "slot": -1,
        } for n in present]
        edges = [(pos[e["company_id_1"]], pos[e["company_id_2"]], int(e["weight"]))
                 for e in es]
        panels.append({
            "period": name.replace("_", "\u2013").replace("pre\u2013", "pre-")
                          .replace("post\u2013", "post-"),
            "nodes": nodes, "edges": edges,
            "n_firms": len(present),
            "n_edges_total": len(by_period.get(name, [])),
        })
    return panels


def build_ego(companies, focus_name, min_weight, w, h):
    """One firm's interlock neighbourhood, labelled."""
    import networkx as nx

    G = build_interlock_graph(min_weight)
    def norm(t: str) -> str:
        # The sources mix straight and curly apostrophes: "Banque de l'Indochine"
        # and "Banque de l’Indochine" are the same firm.
        return t.lower().replace("\u2019", "'").replace("\u2018", "'")

    target = None
    want = norm(focus_name)
    for cid, rec in companies.items():
        if want in norm(rec.get("name") or "") and cid in G:
            if target is None or G.degree(cid) > G.degree(target):
                target = cid
    if target is None:
        return None
    ego = nx.ego_graph(G, target, radius=1)
    if ego.number_of_nodes() > 46:
        wdeg = dict(ego.degree(weight="weight"))
        keep = sorted(wdeg, key=lambda n: -wdeg[n])[:46]
        if target not in keep:
            keep[-1] = target
        ego = ego.subgraph(keep).copy()
    pos = normalise(layout(ego, seed=3, iterations=240), w, h, pad=48, pad_x=LABEL_MARGIN)
    wdeg = dict(ego.degree(weight="weight"))
    lo, hi = min(wdeg.values()), max(wdeg.values())
    nodes = [{
        "id": n,
        "label": (companies.get(n, {}).get("name") or n),
        "territory": territory_of(companies.get(n, {})),
        "slot": -1 if n != target else 0,
        "wdeg": wdeg[n], "degree": ego.degree(n),
        "x": pos[n][0], "y": pos[n][1],
        "r": radius(wdeg[n], lo, hi) * (1.5 if n == target else 1.0),
    } for n in ego.nodes()]
    edges = [(pos[a], pos[b], d["weight"]) for a, b, d in ego.edges(data=True)]
    return {"target": target,
            "target_name": companies.get(target, {}).get("name", target),
            "nodes": nodes, "edges": edges}


# --- page -----------------------------------------------------------------
PANEL_W, PANEL_H = 300, 250
PANELS_W, PANELS_H = 970, 610


def panels_svg(panels, mode: str) -> str:
    """Small multiples, three to a row, each captioned with its tie count."""
    p = PALETTE[mode]
    pw, ph = PANEL_W, PANEL_H
    out = []
    for i, panel in enumerate(panels):
        ox = (i % 3) * (pw + 22)
        oy = (i // 3) * (ph + 52)
        nodes = [dict(n, color=p["series"][0]) for n in panel["nodes"]]
        out.append(f'<g transform="translate({ox},{oy})">')
        out.append(f'<rect width="{pw}" height="{ph}" fill="none" stroke="{p["hairline"]}"/>')
        out.append(draw_network(nodes, panel["edges"], pw, ph, mode))
        out.append(
            f'<text x="0" y="{ph + 18}" font-size="12.5" font-weight="600" '
            f'font-family="ui-sans-serif,system-ui,sans-serif" fill="{p["text_primary"]}">'
            f'{esc(panel["period"])}</text>'
            f'<text x="0" y="{ph + 34}" font-size="11.5" '
            f'font-family="ui-sans-serif,system-ui,sans-serif" fill="{p["text_secondary"]}">'
            f'{panel["n_edges_total"]:,} ties</text>'
        )
        out.append("</g>")
    return "\n".join(out)


def render_page(core_nodes, core_edges, top3, panels, ego, stats) -> str:
    n_union = max((p["n_firms"] for p in panels), default=0)
    lp, dp = PALETTE["light"], PALETTE["dark"]
    W, H = CORE_W, CORE_H

    def core_svg(mode):
        nodes = colourise([dict(n) for n in core_nodes], mode)
        return draw_network(nodes, core_edges, W, H, mode, label_top=14, font=11.5,
                            label_margin=LABEL_MARGIN)

    def ego_svg(mode):
        p = PALETTE[mode]
        nodes = [dict(n, color=p["series"][0] if n["slot"] == 0 else p["other"])
                 for n in ego["nodes"]]
        return draw_network(nodes, ego["edges"], EGO_W, EGO_H, mode, label_top=16, font=11,
                            label_margin=LABEL_MARGIN)

    node_json = json.dumps({n["id"]: {
        "name": n["label"], "territory": n["territory"], "degree": n["degree"],
        "wdeg": n["wdeg"], "sectors": n.get("sectors", ""), "years": n.get("years", ""),
        "n_directors": n.get("n_directors", ""),
    } for n in core_nodes})

    legend_items = "".join(
        f'<span class="lg" role="listitem"><i style="background:var(--s{i+1})"></i>{esc(t)}</span>'
        for i, t in enumerate(top3)
    ) + '<span class="lg" role="listitem"><i style="background:var(--other)"></i>Other territory</span>'

    table_rows = "".join(
        f"<tr><td>{esc(n['label'])}</td><td>{esc(n['territory'])}</td>"
        f"<td class='n'>{n['degree']}</td><td class='n'>{n['wdeg']}</td>"
        f"<td>{esc(n.get('sectors',''))}</td></tr>"
        for n in sorted(core_nodes, key=lambda n: -n["wdeg"])
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Interlocking directorates in French colonial companies</title>
<style>
  .viz-root {{
    color-scheme: light;
    --surface-1: {lp['surface']}; --text-primary: {lp['text_primary']};
    --text-secondary: {lp['text_secondary']}; --text-muted: {lp['text_muted']};
    --hairline: {lp['hairline']};
    --s1: {lp['series'][0]}; --s2: {lp['series'][1]}; --s3: {lp['series'][2]};
    --other: {lp['other']};
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
      color-scheme: dark;
      --surface-1: {dp['surface']}; --text-primary: {dp['text_primary']};
      --text-secondary: {dp['text_secondary']}; --text-muted: {dp['text_muted']};
      --hairline: {dp['hairline']};
      --s1: {dp['series'][0]}; --s2: {dp['series'][1]}; --s3: {dp['series'][2]};
      --other: {dp['other']};
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
    color-scheme: dark;
    --surface-1: {dp['surface']}; --text-primary: {dp['text_primary']};
    --text-secondary: {dp['text_secondary']}; --text-muted: {dp['text_muted']};
    --hairline: {dp['hairline']};
    --s1: {dp['series'][0]}; --s2: {dp['series'][1]}; --s3: {dp['series'][2]};
    --other: {dp['other']};
  }}
  html,body {{ margin:0; padding:0; }}
  .viz-root {{
    background: var(--surface-1); color: var(--text-primary);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 34px clamp(16px,4vw,56px) 72px; min-height:100vh;
  }}
  h1 {{ font-size: 25px; font-weight: 620; margin: 0 0 6px; letter-spacing: -.01em; }}
  h2 {{ font-size: 17px; font-weight: 600; margin: 46px 0 4px; letter-spacing: -.005em; }}
  p.sub {{ color: var(--text-secondary); font-size: 14px; margin: 0 0 4px; max-width: 74ch; line-height:1.5; }}
  p.note {{ color: var(--text-muted); font-size: 12.5px; margin: 6px 0 0; max-width: 82ch; line-height:1.5; }}
  .bar {{ display:flex; gap:18px; align-items:center; flex-wrap:wrap; margin:14px 0 10px; }}
  .legend {{ display:inline-flex; align-items:center; gap:16px; flex-wrap:wrap; }}
  .lg {{ display:inline-flex; align-items:center; gap:7px; font-size:13px; color:var(--text-secondary); }}
  .lg i {{ width:11px; height:11px; border-radius:50%; display:inline-block; }}
  button {{ font:inherit; font-size:12.5px; color:var(--text-secondary); background:transparent;
    border:1px solid var(--hairline); border-radius:7px; padding:5px 11px; cursor:pointer; }}
  button:hover {{ color:var(--text-primary); }}
  .fig {{ position:relative; margin-top:8px; }}
  .fig svg {{ display:block; width:100%; height:auto; }}
  .dark-only {{ display:none; }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .light-only {{ display:none; }}
    :root:where(:not([data-theme="light"])) .dark-only {{ display:block; }}
  }}
  :root[data-theme="dark"] .light-only {{ display:none; }}
  :root[data-theme="dark"] .dark-only {{ display:block; }}
  #tip {{ position:fixed; pointer-events:none; opacity:0; transition:opacity .1s;
    background:var(--surface-1); color:var(--text-primary); border:1px solid var(--hairline);
    border-radius:9px; padding:9px 11px; font-size:12.5px; line-height:1.45;
    box-shadow:0 6px 22px rgba(0,0,0,.16); max-width:290px; z-index:9; }}
  #tip b {{ font-weight:620; }}
  #tip span {{ color:var(--text-secondary); }}
  .nd {{ cursor:pointer; }}
  table {{ border-collapse:collapse; font-size:12.5px; margin-top:12px; width:100%; }}
  th,td {{ text-align:left; padding:5px 10px; border-bottom:1px solid var(--hairline); }}
  th {{ color:var(--text-secondary); font-weight:600; }}
  td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  #tablewrap {{ display:none; max-height:460px; overflow:auto; margin-top:10px;
    border:1px solid var(--hairline); border-radius:9px; }}
  .stat {{ display:flex; gap:38px; flex-wrap:wrap; margin:16px 0 2px; }}
  .stat div span {{ display:block; font-size:12.5px; color:var(--text-secondary); }}
  .stat div b {{ font-size:26px; font-weight:620; letter-spacing:-.01em; }}
</style></head>
<body><div class="viz-root">

<h1>Interlocking directorates in French colonial companies</h1>
<p class="sub">Two firms are linked when the same person sat on both boards.
Built from {stats['n_ties']:,} dated board observations in
{stats['n_docs']:,} dossiers from entreprises-coloniales.fr.</p>

<div class="stat">
  <div><b>{stats['n_firms']:,}</b><span>firms with a board</span></div>
  <div><b>{stats['n_people']:,}</b><span>directors</span></div>
  <div><b>{stats['n_interlocks']:,}</b><span>interlock ties</span></div>
  <div><b>{stats['pct_native']}</b><span>directors with an indigenous name</span></div>
</div>

<h2>The core of the network</h2>
<p class="sub">Firms sharing at least two directors, largest component, the
{len(core_nodes)} most connected shown. Colour is territory; node size is the
number of shared directorships. Hover any node for detail.</p>
<div class="bar"><span class="legend" role="list" aria-label="Legend: territory">{legend_items}</span>
  <button id="tbtn" aria-expanded="false">Show data table</button>
  <button id="theme">Toggle dark mode</button>
</div>
<div class="fig">
  <div class="light-only">{svg_document(core_svg('light'), W, H, 'light', 'Core interlock network')}</div>
  <div class="dark-only">{svg_document(core_svg('dark'), W, H, 'dark', 'Core interlock network')}</div>
</div>
<p class="note">Edge opacity and thickness rise with the number of shared
directors. The full graph ({stats['n_interlocks']:,} ties over {stats['n_firms_graph']:,}
firms) is not drawn: at that size a node-link diagram is an unreadable
hairball, so the figure shows its core and the table carries the rest.</p>
<div id="tablewrap"><table><thead><tr><th>Firm</th><th>Territory</th>
<th class="n">Interlocks</th><th class="n">Shared directorships</th><th>Sector</th>
</tr></thead><tbody>{table_rows}</tbody></table></div>

<h2>How the network changed over time</h2>
<p class="sub">All five panels share one layout and one size scale, so a firm
sits in the same place throughout and the panels can be compared directly.
Colonial corporate interlocking peaks between the wars and contracts sharply
after 1945.</p>
<div class="fig">
  <div class="light-only">{svg_document(panels_svg(panels, 'light'), PANELS_W, PANELS_H, 'light', 'Interlock networks by period')}</div>
  <div class="dark-only">{svg_document(panels_svg(panels, 'dark'), PANELS_W, PANELS_H, 'dark', 'Interlock networks by period')}</div>
</div>
<p class="note">A tie here is two firms sharing at least two directors within
that period; the count is every such tie in the period, and the panel draws
those among the {n_union} best-connected firms overall. A firm absent from a
panel had no recorded shared directorship then — which may mean the source
does not report its board, not that it had none.</p>

<h2>One firm's neighbourhood: {esc(ego['target_name'])}</h2>
<p class="sub">Every firm sharing a director with it, sized by their own
connectedness.</p>
<div class="fig">
  <div class="light-only">{svg_document(ego_svg('light'), EGO_W, EGO_H, 'light', 'Ego network')}</div>
  <div class="dark-only">{svg_document(ego_svg('dark'), EGO_W, EGO_H, 'dark', 'Ego network')}</div>
</div>

<p class="note" style="margin-top:34px">Source: entreprises-coloniales.fr,
compiled by its editor; extraction pipeline and codebook in this repository.
Coverage is uneven by territory and period, so absence of a tie is not
evidence of absence of a relationship — see docs/METHODOLOGY.md §6.</p>

<div id="tip" class="tooltip" role="status" aria-live="polite"></div>
</div>
<script>
const DATA = {node_json};
const tip = document.getElementById('tip');
function show(e, id) {{
  const d = DATA[id]; if (!d) return;
  tip.innerHTML = '<b>' + d.name + '</b><br><span>' + d.territory + '</span><br>' +
    d.degree + ' interlocks &middot; ' + d.wdeg + ' shared directorships' +
    (d.n_directors ? '<br><span>' + d.n_directors + ' directors recorded</span>' : '') +
    (d.years && d.years !== '-' ? '<br><span>observed ' + d.years + '</span>' : '') +
    (d.sectors ? '<br><span>' + d.sectors + '</span>' : '');
  tip.style.opacity = 1;
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + w > innerWidth - 8) x = e.clientX - w - pad;
  if (y + h > innerHeight - 8) y = e.clientY - h - pad;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}}
document.querySelectorAll('.nd').forEach(el => {{
  el.addEventListener('mousemove', e => show(e, el.dataset.id));
  el.addEventListener('mouseleave', () => tip.style.opacity = 0);
  el.setAttribute('tabindex', '0');
  el.addEventListener('focus', e => {{
    const r = el.getBoundingClientRect();
    show({{clientX: r.left + r.width/2, clientY: r.top}}, el.dataset.id);
  }});
  el.addEventListener('blur', () => tip.style.opacity = 0);
}});
const tw = document.getElementById('tablewrap'), tb = document.getElementById('tbtn');
tb.addEventListener('click', () => {{
  const open = tw.style.display === 'block';
  tw.style.display = open ? 'none' : 'block';
  tb.textContent = open ? 'Show data table' : 'Hide data table';
  tb.setAttribute('aria-expanded', String(!open));
}});
document.getElementById('theme').addEventListener('click', () => {{
  const cur = document.documentElement.getAttribute('data-theme');
  const dark = cur ? cur === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
}});
</script></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=170, help="nodes in the core figure")
    ap.add_argument("--min-weight", type=int, default=2,
                    help="minimum shared directors for an edge to be drawn")
    ap.add_argument("--ego", default="Banque de l'Indochine")
    args = ap.parse_args()

    ensure_dir(FIG_DIR)
    companies = {r["company_id"]: r for r in read_csv("companies.csv")}
    W, H = CORE_W, CORE_H

    core_nodes, core_edges, top3, K = prepare_core(
        companies, args.top, args.min_weight, W, H)
    panels = build_period_panels(companies, args.min_weight, 150, 300, 250)
    ego = build_ego(companies, args.ego, args.min_weight, EGO_W, EGO_H)
    if ego is None:
        raise SystemExit(f"no firm matching {args.ego!r} in the interlock graph")

    people = read_csv("persons_resolved.csv")
    pos_rows = read_csv("person_positionality.csv")
    native = sum(1 for r in pos_rows if r["positionality"] == "native")
    full = build_interlock_graph(args.min_weight)
    stats = {
        "n_firms": len(companies),
        "n_people": len(people),
        "n_interlocks": len(read_csv("edges_company_interlock.csv")),
        "n_ties": len(read_csv("edges_person_company.csv")),
        "n_docs": len(read_csv("documents.csv")),
        "n_firms_graph": full.number_of_nodes(),
        "pct_native": f"{100 * native / len(pos_rows):.1f}%" if pos_rows else "n/a",
    }

    page = render_page(core_nodes, core_edges, top3, panels, ego, stats)
    out = os.path.join(FIG_DIR, "interlock_network.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {os.path.relpath(out, ROOT)}", file=sys.stderr)

    # Standalone SVGs for papers, light mode. Each carries its own legend and
    # caption: outside the page there is no other place for them, and identity
    # must never rest on colour alone.
    lp = PALETTE["light"]
    core_legend = [(lp["series"][i], t) for i, t in enumerate(top3)]
    core_legend.append((lp["other"], "Other territory"))
    for name, body, w, h, title, legend, caption in [
        ("fig1_core_interlocks",
         draw_network(colourise([dict(n) for n in core_nodes], "light"),
                      core_edges, W, H, "light", label_top=14, font=11.5,
                      label_margin=LABEL_MARGIN),
         W, H, "Core interlock network", core_legend,
         f"{len(core_nodes)} firms, {len(core_edges):,} interlocks at two or more "
         f"shared directors \u2014 the core of a graph of {stats['n_firms_graph']:,} "
         f"firms. Node area is weighted degree."),
        ("fig2_by_period",
         panels_svg(panels, "light"),
         PANELS_W, PANELS_H, "Interlock networks by period", None,
         "One shared layout and one size scale throughout, so panels are comparable."),
        ("fig3_ego_indochine",
         draw_network([dict(n, color=lp["series"][0] if n["slot"] == 0
                            else lp["other"]) for n in ego["nodes"]],
                      ego["edges"], EGO_W, EGO_H, "light", label_top=16, font=11,
                      label_margin=LABEL_MARGIN),
         EGO_W, EGO_H, f"Interlock neighbourhood of {ego['target_name']}",
         [(lp["series"][0], ego["target_name"]), (lp["other"], "Interlocked firm")],
         f"{len(ego['nodes']) - 1} firms sharing at least two directors with "
         f"{ego['target_name']}."),
    ]:
        path = os.path.join(FIG_DIR, f"{name}.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg_document(body, w, h, "light", title, legend, caption))
        print(f"wrote {os.path.relpath(path, ROOT)}", file=sys.stderr)

    print(f"\ncore figure: {len(core_nodes)} firms, {len(core_edges)} interlocks, "
          f"territories {top3}", file=sys.stderr)
    for p in panels:
        print(f"  {p['period']:12s} {p['n_edges_total']:6,} interlocks", file=sys.stderr)


if __name__ == "__main__":
    main()
