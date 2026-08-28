"""Stage 8 - the whole empire, and one figure per territory.

    figures/fig4_empire_network.svg      every firm in the interlock graph
    figures/fig5_territory_matrix.svg    territory x territory shared directors
    figures/by_country/<slug>.svg        one figure per territory
    figures/territory_networks.html      all of the above, hover + dark mode

Three things distinguish these from the core figures of stage 7:

- **Nothing is subsetted.** Figure 4 draws all 3,085 firms and 39,523
  interlocks at weight >= 1, including the 46 firms outside the giant
  component, which are placed in a strip rather than dropped. A graph this
  dense cannot be read firm by firm and is not meant to be: it answers whether
  the empire's boards form one integrated elite or separate territorial ones.
  For anything firm-level, use figure 1 or the per-territory figures.
- **A dense graph is better read as a matrix.** Figure 5 aggregates to the
  territory level, where 54 nodes and near-complete connectivity would make a
  node-link diagram useless. The cell is the number of directors sitting on
  boards in both territories - the empire network at the level where it is
  legible, and the one figure here that carries a quantity, so it uses a
  sequential ramp rather than categorical hues.
- **Per-territory figures use one hue, not a palette.** Within a territory
  there is no second category to encode, and a single series needs no legend:
  the title names it.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_figures import (  # noqa: E402
    FIG_DIR, LABEL_MARGIN, PALETTE, ROOT, build_interlock_graph, draw_network,
    esc, layout, normalise, radius, svg_document, territory_of, trim_to_width,
)
from build_network import read_csv  # noqa: E402
from common import ensure_dir  # noqa: E402

EMPIRE_W, EMPIRE_H = 1500.0, 1000.0
STRIP_H = 74.0          # band along the bottom for the residual components
TERR_W, TERR_H = 1120.0, 640.0
TERR_MARGIN = 236.0

# Sequential ramp for the matrix: one hue, light to dark. Never a rainbow -
# the cell carries a magnitude, and a categorical palette would invent
# boundaries between counts that differ by one.
SEQ = {
    "light": ["#f2f6fd", "#d7e5f9", "#b0cbf1", "#7fa9e5", "#4f86dc",
              "#2a78d6", "#1d5aa4", "#143f74"],
    "dark": ["#1f2a3a", "#23384f", "#2a4a6b", "#31608c", "#3778b5",
             "#3987e5", "#6aa8ee", "#9cc6f5"],
}
# Same trick as PALETTE["vars"]: one matrix serves both themes in the page.
SEQ["vars"] = [f"var(--q{i + 1})" for i in range(len(SEQ["light"]))]


def layout_with_strip(G, width, height, pad, pad_x, seed, iterations,
                      robust=0.0, strip_h=STRIP_H):
    """Lay out the giant component to fill the canvas; strip the rest.

    A spring layout on a disconnected graph pushes the components apart, and
    normalising to their joint extent then shrinks the giant component - the
    part worth looking at - into a blob in the middle. Senegal's 39-firm main
    component was rendered at a quarter of the canvas by three stragglers.
    Laying the giant component out alone and packing the residue into a band
    along the bottom keeps every firm in the figure without that cost.
    """
    import networkx as nx

    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    giant = G.subgraph(comps[0]).copy()
    rest = [sorted(c) for c in comps[1:]]
    body_h = height - (strip_h if rest else 0.0)
    pos = normalise(layout(giant, seed=seed, iterations=iterations),
                    width, body_h, pad=pad, pad_x=pad_x, robust=robust)
    if rest:
        slot = (width - 80) / len(rest)
        for i, comp in enumerate(rest):
            cx = 40 + slot * (i + 0.5)
            cy = body_h + strip_h / 2
            gap = min(13.0, max(5.0, slot / (len(comp) + 1)))
            for j, n in enumerate(comp):
                pos[n] = (cx + (j - (len(comp) - 1) / 2) * gap, cy)
    return pos, {"n_components": len(comps), "n_giant": len(comps[0]),
                 "n_residual": sum(len(c) for c in rest), "body_h": body_h,
                 "has_strip": bool(rest)}


def strip_rule(meta, width, mode, note):
    """The hairline that separates the residue from the giant component, so
    the strip is never read as the periphery of the main graph."""
    if not meta["has_strip"]:
        return ""
    p = PALETTE[mode]
    y = meta["body_h"] + 6
    # The note sits above the rule: the packed components run the full width
    # below it, and a note inside the strip collides with them.
    return (
        f'<line x1="40" y1="{y:.0f}" x2="{width - 40:.0f}" y2="{y:.0f}" '
        f'stroke="{p["hairline"]}" stroke-width="1"/>'
        f'<text x="{width - 40:.0f}" y="{y - 5:.0f}" text-anchor="end" font-size="11" '
        f'font-family="ui-sans-serif,system-ui,sans-serif" fill="{p["text_muted"]}">'
        f'{esc(note)}</text>'
    )


# --- figure 4: the whole interlock graph ----------------------------------
def build_empire(companies, width, height):
    """Every firm in the interlock graph, giant component plus the residue.

    The giant component holds 98.5% of the firms. The remaining 46 sit in 22
    tiny components that a spring layout would fling into the corners, so they
    are packed into a strip along the bottom instead of being dropped: a
    figure captioned "every firm" has to contain every firm.
    """
    G = build_interlock_graph(1)
    pos, meta = layout_with_strip(G, width, height, pad=38, pad_x=LABEL_MARGIN,
                                  seed=7, iterations=120, robust=0.015)

    terr = Counter(territory_of(companies.get(n, {})) for n in G.nodes())
    top3 = [t for t, _ in terr.most_common(3)]
    slot_of = {t: i for i, t in enumerate(top3)}

    wdeg = dict(G.degree(weight="weight"))
    lo, hi = min(wdeg.values()), max(wdeg.values())
    nodes = []
    for n in G.nodes():
        rec = companies.get(n, {})
        t = territory_of(rec)
        nodes.append({
            "id": n,
            "label": rec.get("name") or n,
            "territory": t,
            "slot": slot_of.get(t, -1),
            "wdeg": wdeg[n],
            "degree": G.degree(n),
            "x": pos[n][0], "y": pos[n][1],
            # A third of the core figure's radii: 3,085 nodes at full size is
            # solid ink, and the shape of the graph is what this figure shows.
            "r": max(1.3, (radius(wdeg[n], lo, hi) - 3.2) * 0.42 + 1.3),
        })
    edges = [(pos[a], pos[b], d["weight"]) for a, b, d in G.edges(data=True)]
    return dict(
        meta, nodes=nodes, edges=edges, top3=top3,
        n_firms=G.number_of_nodes(), n_edges=G.number_of_edges(),
        shares={t: terr[t] / G.number_of_nodes() for t in top3},
    )


def strip_note(meta):
    return (f'{meta["n_residual"]} firms in {meta["n_components"] - 1} '
            f'component{"s" if meta["n_components"] != 2 else ""} unconnected '
            f'to the main graph')


def empire_svg(empire, mode, label_top=16):
    p = PALETTE[mode]
    nodes = [dict(n, color=p["series"][n["slot"]] if n["slot"] >= 0 else p["other"])
             for n in empire["nodes"]]
    return draw_network(
        nodes, empire["edges"], EMPIRE_W, EMPIRE_H, mode, label_top=label_top,
        font=11.5, label_margin=LABEL_MARGIN, edge_opacity=0.42, node_ring=0.8,
    ) + strip_rule(empire, EMPIRE_W, mode, strip_note(empire))


# --- figure 5: the territory-level matrix ---------------------------------
def territory_person_sets(level="country"):
    """Directors per territory. A firm listed in two territories puts its
    board in both, which is the tie the matrix is about."""
    field = "countries" if level == "country" else "regions"
    firm_terr = {}
    n_firms = Counter()
    for c in read_csv("companies.csv"):
        ts = [t for t in (c.get(field) or "").split("; ") if t]
        firm_terr[c["company_id"]] = ts
        for t in ts:
            n_firms[t] += 1
    people = defaultdict(set)
    for e in read_csv("edges_person_company.csv"):
        if e["is_board_seat"] != "1":
            continue
        for t in firm_terr.get(e["company_id"], ()):
            people[t].add(e["person_id"])
    return people, n_firms


def build_matrix(min_people=8):
    """Territory x territory shared directors, ordered by size."""
    people, n_firms = territory_person_sets("country")
    terrs = [t for t in people if len(people[t]) >= min_people]
    terrs.sort(key=lambda t: -len(people[t]))
    cells = {}
    hi = 0
    for i, a in enumerate(terrs):
        for b in terrs[i + 1:]:
            n = len(people[a] & people[b])
            if n:
                cells[(a, b)] = n
                hi = max(hi, n)
    return {"territories": terrs, "cells": cells, "hi": hi,
            "n_people": {t: len(people[t]) for t in terrs},
            "n_firms": {t: n_firms[t] for t in terrs},
            "dropped": sorted(t for t in people if t not in terrs)}


CELL = 17.0
MATRIX_LABEL = 236.0
MATRIX_FONT = 11.0


def matrix_svg(m, mode):
    p = PALETTE[mode]
    seq = SEQ[mode]
    ts = m["territories"]
    n = len(ts)
    grid = n * CELL
    out = [f'<g transform="translate({MATRIX_LABEL},{MATRIX_LABEL})">']
    # Cells. The scale is by rank within the observed range rather than
    # linear: shared-director counts are heavily skewed, and a linear ramp
    # would leave everything but Indochine-Maroc in the palest step.
    vals = sorted(set(m["cells"].values()))
    for (a, b), v in m["cells"].items():
        i, j = ts.index(a), ts.index(b)
        step = min(len(seq) - 1, int(len(seq) * (vals.index(v) + 1) / len(vals)))
        colour = seq[step]
        for x, y in ((j, i), (i, j)):     # symmetric, both triangles drawn
            out.append(
                f'<rect class="mc" data-a="{esc(a)}" data-b="{esc(b)}" data-v="{v}" '
                f'x="{x * CELL:.1f}" y="{y * CELL:.1f}" '
                f'width="{CELL - 2:.1f}" height="{CELL - 2:.1f}" fill="{colour}"/>'
            )
    # Diagonal, marked as not-a-count so it is never read as a shared total.
    for i in range(n):
        out.append(
            f'<rect x="{i * CELL:.1f}" y="{i * CELL:.1f}" width="{CELL - 2:.1f}" '
            f'height="{CELL - 2:.1f}" fill="none" stroke="{p["hairline"]}"/>'
        )
    out.append("</g>")
    # Row labels left, column labels rotated above.
    out.append(f'<g font-size="{MATRIX_FONT}" '
               f'font-family="ui-sans-serif,system-ui,sans-serif" '
               f'fill="{p["text_secondary"]}">')
    for i, t in enumerate(ts):
        # Both axes read outward from the grid, so both are bounded by the
        # same margin. Soudan francais's full label is 65 characters and ran
        # clean off the canvas before this.
        label = trim_to_width(t, MATRIX_FONT, MATRIX_LABEL - 12)
        y = MATRIX_LABEL + i * CELL + CELL / 2 + 3
        out.append(f'<text x="{MATRIX_LABEL - 8:.0f}" y="{y:.1f}" '
                   f'text-anchor="end">{esc(label)}</text>')
        x = MATRIX_LABEL + i * CELL + CELL / 2 + 4
        # Default (start) anchor: rotated -90, the label grows upward out of
        # the grid. An end anchor grows it downward, straight over the cells.
        out.append(f'<text x="{x:.1f}" y="{MATRIX_LABEL - 8:.0f}" '
                   f'transform="rotate(-90 {x:.1f} {MATRIX_LABEL - 8:.0f})">'
                   f'{esc(label)}</text>')
    out.append("</g>")
    # Sequential legend with its endpoints labelled.
    ly = MATRIX_LABEL + grid + 34
    out.append(f'<g font-size="11.5" font-family="ui-sans-serif,system-ui,sans-serif" '
               f'fill="{p["text_secondary"]}">')
    out.append(f'<text x="{MATRIX_LABEL:.0f}" y="{ly - 12:.0f}">'
               f'Directors sitting on boards in both territories</text>')
    for k, colour in enumerate(seq):
        out.append(f'<rect x="{MATRIX_LABEL + k * 26:.0f}" y="{ly:.0f}" width="24" '
                   f'height="11" fill="{colour}"/>')
    out.append(f'<text x="{MATRIX_LABEL:.0f}" y="{ly + 26:.0f}">fewest</text>')
    out.append(f'<text x="{MATRIX_LABEL + len(seq) * 26 - 2:.0f}" y="{ly + 26:.0f}" '
               f'text-anchor="end">most ({m["hi"]:,})</text>')
    out.append("</g>")
    return "\n".join(out), MATRIX_LABEL + grid + 8, MATRIX_LABEL + grid + 70


# --- per-territory figures -------------------------------------------------
def bundle_dir(level: str) -> str:
    return os.path.join(ROOT, "data", f"by_{level}")


def read_bundle_edges(level, slug):
    path = os.path.join(bundle_dir(level), slug, "edges_company_interlock.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def territory_height(n_firms: int) -> float:
    """A 2-firm graph in a 640px box is 98% white space. Scale the canvas to
    the graph rather than padding every territory out to the largest."""
    return TERR_H if n_firms >= 25 else 420.0 if n_firms >= 8 else 250.0


def build_territory(level, slug, name, width, height=None, n_in_bundle=0):
    """One territory's complete interlock graph - no threshold, no top-N."""
    import networkx as nx

    rows = read_bundle_edges(level, slug)
    if not rows:
        return None
    G = nx.Graph()
    names = {}
    for e in rows:
        G.add_edge(e["company_id_1"], e["company_id_2"], weight=int(e["weight"]))
        names[e["company_id_1"]] = e["company_name_1"]
        names[e["company_id_2"]] = e["company_name_2"]

    n = G.number_of_nodes()
    height = territory_height(n) if height is None else height
    pos, meta = layout_with_strip(G, width, height, pad=30, pad_x=TERR_MARGIN,
                                  seed=11, iterations=200,
                                  robust=0.02 if n > 60 else 0.0,
                                  strip_h=58.0)
    wdeg = dict(G.degree(weight="weight"))
    lo, hi = min(wdeg.values()), max(wdeg.values())
    # Big territories need smaller marks or the core is one solid disc; small
    # ones need bigger, or a 12-firm network is a scatter of specks.
    scale, floor = (0.62, 2.0) if n >= 250 else (1.0, 3.4) if n >= 60 else (1.25, 4.4)
    nodes = [{
        "id": n_,
        "label": names.get(n_, n_),
        "wdeg": wdeg[n_], "degree": G.degree(n_),
        "x": pos[n_][0], "y": pos[n_][1],
        "r": max(floor, (radius(wdeg[n_], lo, hi) - 3.2) * scale + floor),
    } for n_ in G.nodes()]
    edges = [(pos[a], pos[b], d["weight"]) for a, b, d in G.edges(data=True)]
    return dict(
        meta, slug=slug, name=name, nodes=nodes, edges=edges, height=height,
        n_firms=n, n_edges=G.number_of_edges(), n_in_bundle=n_in_bundle,
        top=sorted(nodes, key=lambda x: -x["wdeg"])[:5],
    )


def territory_svg(t, mode, label_top=11):
    p = PALETTE[mode]
    nodes = [dict(n, color=p["series"][0]) for n in t["nodes"]]
    # Dense territories drown in edge ink at the core figure's settings.
    op = 0.55 if t["n_edges"] > 1200 else 0.8 if t["n_edges"] > 300 else 1.0
    return draw_network(
        nodes, t["edges"], TERR_W, t["height"], mode,
        label_top=min(label_top, len(nodes)), font=10.5,
        label_margin=TERR_MARGIN, edge_opacity=op,
        node_ring=1.2 if t["n_firms"] >= 250 else 2.0,
    ) + strip_rule(t, TERR_W, mode, strip_note(t))


def plural(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def territory_caption(t):
    of_bundle = ""
    rest = t["n_in_bundle"] - t["n_firms"] if t["n_in_bundle"] else 0
    if rest > 0:
        of_bundle = (f" The other {plural(rest, 'firm')} in this territory's "
                     f"bundle share{'s' if rest == 1 else ''} no director with "
                     f"another and so ha{'s' if rest == 1 else 've'} no place in "
                     f"an interlock network.")
    n_lab = min(11, t["n_firms"])
    return (f"{plural(t['n_firms'], 'firm')}, {plural(t['n_edges'], 'interlock')}, "
            f"{plural(t['n_components'], 'component')} "
            f"(largest {t['n_giant']:,}). Node area is weighted degree; the "
            f"{n_lab} best-connected are labelled.{of_bundle}"
            if n_lab < t["n_firms"] else
            f"{plural(t['n_firms'], 'firm')}, {plural(t['n_edges'], 'interlock')}, "
            f"{plural(t['n_components'], 'component')} "
            f"(largest {t['n_giant']:,}). Node area is weighted degree; every "
            f"firm is labelled.{of_bundle}")


def load_manifest(level):
    path = os.path.join(bundle_dir(level), "territory_manifest.csv")
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# --- the gallery page ------------------------------------------------------
def render_gallery(empire, matrix, territories, empty, level) -> str:
    lp, dp = PALETTE["light"], PALETTE["dark"]
    seq_light = "".join(f"    --q{i + 1}:{c};\n" for i, c in enumerate(SEQ["light"]))
    seq_dark = "".join(f"    --q{i + 1}:{c};\n" for i, c in enumerate(SEQ["dark"]))
    m_body, m_h, m_total = matrix_svg(matrix, "vars")

    emp_legend = "".join(
        f'<span class="lg" role="listitem"><i style="background:var(--s{i + 1})"></i>'
        f'{esc(t)} ({empire["shares"][t] * 100:.0f}%)</span>'
        for i, t in enumerate(empire["top3"])
    ) + ('<span class="lg" role="listitem"><i style="background:var(--other)"></i>'
         'Other territory</span>')

    node_json = json.dumps({n["id"]: [n["label"], n["territory"], n["degree"],
                                      int(n["wdeg"])] for n in empire["nodes"]})

    cards = []
    for t in territories:
        top = ", ".join(esc(n["label"]) for n in t["top"][:3])
        cards.append(f"""
<section class="card" id="t-{esc(t['slug'])}">
  <h3>{esc(t['name'])}</h3>
  <p class="sub">{esc(territory_caption(t))}</p>
  <div class="fig">
    {svg_document(territory_svg(t, 'vars'), TERR_W, t['height'], 'vars', esc(t['name']) + ' interlock network')}
  </div>
  <p class="note">Best connected: {top}. <a href="by_country/{esc(t['slug'])}.svg">SVG</a></p>
</section>""")

    toc = " ".join(
        f'<a href="#t-{esc(t["slug"])}">{esc(t["name"])} <b>{t["n_firms"]}</b></a>'
        for t in territories)

    rows = "".join(
        f"<tr><td>{esc(t['name'])}</td><td>{t['n_firms']:,}</td>"
        f"<td>{t['n_edges']:,}</td><td>{t['n_components']}</td>"
        f"<td>{t['n_giant']:,}</td></tr>"
        for t in territories)

    empty_note = ""
    if empty:
        empty_note = (
            "<p class=\"note\">No figure for "
            + ", ".join(esc(e) for e in empty)
            + " — each has firms in the dataset but no two of them share a "
              "director, so there is no network to draw. That is a statement "
              "about the collection's coverage, not about the territory.</p>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The empire network, and one figure per territory</title>
<style>
  :root {{
    --surface:{lp['surface']}; --text-primary:{lp['text_primary']};
    --text-secondary:{lp['text_secondary']}; --text-muted:{lp['text_muted']};
    --hairline:{lp['hairline']}; --s1:{lp['series'][0]}; --s2:{lp['series'][1]};
    --s3:{lp['series'][2]}; --other:{lp['other']}; --edge:{lp['edge']};
{seq_light}  }}
  html[data-theme="dark"] {{
    --surface:{dp['surface']}; --text-primary:{dp['text_primary']};
    --text-secondary:{dp['text_secondary']}; --text-muted:{dp['text_muted']};
    --hairline:{dp['hairline']}; --s1:{dp['series'][0]}; --s2:{dp['series'][1]};
    --s3:{dp['series'][2]}; --other:{dp['other']}; --edge:{dp['edge']};
{seq_dark}  }}
  @media (prefers-color-scheme: dark) {{
    html:not([data-theme="light"]) {{
      --surface:{dp['surface']}; --text-primary:{dp['text_primary']};
      --text-secondary:{dp['text_secondary']}; --text-muted:{dp['text_muted']};
      --hairline:{dp['hairline']}; --s1:{dp['series'][0]}; --s2:{dp['series'][1]};
      --s3:{dp['series'][2]}; --other:{dp['other']}; --edge:{dp['edge']};
{seq_dark}    }}
  }}
  body {{ margin:0; padding:34px 30px 90px; background:var(--surface);
    color:var(--text-primary); font:15px/1.55 ui-sans-serif,system-ui,sans-serif;
    max-width:1560px; }}
  h1 {{ font-size:27px; letter-spacing:-.01em; margin:0 0 6px; }}
  h2 {{ font-size:20px; margin:52px 0 4px; }}
  h3 {{ font-size:16px; margin:0 0 3px; }}
  p.sub {{ color:var(--text-secondary); margin:0 0 14px; max-width:74ch; }}
  p.note {{ color:var(--text-muted); font-size:13px; margin:8px 0 0; max-width:80ch; }}
  a {{ color:var(--s1); }}
  .fig {{ overflow-x:auto; border:1px solid var(--hairline); border-radius:8px;
    background:var(--surface); }}
  .fig svg {{ display:block; max-width:100%; height:auto; }}
  .bar {{ display:flex; align-items:center; gap:16px; flex-wrap:wrap; margin:0 0 12px; }}
  .legend {{ display:inline-flex; align-items:center; gap:16px; flex-wrap:wrap; }}
  .lg {{ display:inline-flex; align-items:center; gap:7px; font-size:13px;
    color:var(--text-secondary); }}
  .lg i {{ width:11px; height:11px; border-radius:50%; display:inline-block; }}
  button {{ font:inherit; font-size:13px; padding:5px 11px; border-radius:7px;
    border:1px solid var(--hairline); background:transparent;
    color:var(--text-secondary); cursor:pointer; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(470px,1fr));
    gap:26px; margin-top:16px; }}
  .card {{ min-width:0; }}
  .toc {{ display:flex; flex-wrap:wrap; gap:6px 12px; margin:10px 0 4px;
    font-size:13px; }}
  .toc a {{ color:var(--text-secondary); text-decoration:none;
    border-bottom:1px solid var(--hairline); }}
  .toc a b {{ color:var(--text-muted); font-weight:500; }}
  table {{ border-collapse:collapse; font-size:13px; margin-top:10px; }}
  th, td {{ text-align:left; padding:4px 16px 4px 0;
    border-bottom:1px solid var(--hairline); }}
  th {{ color:var(--text-secondary); font-weight:600; }}
  td:not(:first-child), th:not(:first-child) {{ text-align:right; }}
  .tooltip {{ position:fixed; pointer-events:none; opacity:0; transition:opacity .1s;
    background:var(--surface); border:1px solid var(--hairline); border-radius:8px;
    padding:7px 10px; font-size:12.5px; box-shadow:0 4px 16px rgba(0,0,0,.13);
    max-width:290px; z-index:9; }}
  .tooltip b {{ font-weight:620; }} .tooltip span {{ color:var(--text-secondary); }}
  .nd:hover, .mc:hover {{ stroke:var(--text-primary); stroke-width:1.4; }}
</style></head>
<body class="viz-root">

<h1>The empire network, and one figure per territory</h1>
<p class="sub">Companion to the core figures. Nothing here is subsetted: figure
4 is every firm in the interlock graph and each territory figure is that
territory's complete graph. <b>Read them for shape and composition, not for
individual firms</b> — at this density the ink is the message.</p>

<div class="bar">
  <button id="theme">Toggle dark mode</button>
  <button id="tbtn" aria-expanded="false">Show data table</button>
</div>

<h2>Figure 4 — every firm, every interlock</h2>
<p class="sub">All {empire['n_firms']:,} firms that share at least one director
with another, and all {empire['n_edges']:,} interlocks between them. The giant
component holds {empire['n_giant']:,} of them ({empire['n_giant'] / empire['n_firms'] * 100:.1f}%);
the rest are in the strip below the rule. Colour is the firm's first territory,
folded to the three largest — the question the figure answers is whether those
three separate or interleave.</p>
<div class="bar"><span class="legend" role="list" aria-label="Legend: territory">{emp_legend}</span></div>
<div class="fig">
  {svg_document(empire_svg(empire, 'vars'), EMPIRE_W, EMPIRE_H, 'vars', 'Empire-wide interlock network')}
</div>
<p class="note">A firm absent here is not a firm without directors — it is a
firm the collection never shows sharing one. Coverage is very uneven by
territory and period; see METHODOLOGY §6.</p>

<h2>Figure 5 — the empire as a network of territories</h2>
<p class="sub">The same data aggregated: each cell is the number of directors
holding board seats in <i>both</i> territories, for the
{len(matrix['territories'])} territories with at least eight directors.
A matrix rather than a node-link diagram because at this level the graph is
small and nearly complete, where a node-link diagram degenerates into a
scribble. The diagonal is outlined, not filled — a territory does not share
directors with itself.</p>
<div class="fig">
  {svg_document(m_body, MATRIX_LABEL + len(matrix['territories']) * CELL + 40, m_total, 'vars', 'Shared directors between territories')}
</div>
<p class="note">Shading steps by rank, not linearly — the counts are
heavily skewed, so a linear ramp would leave every pair but the top few in the
palest step. Hover a cell for the actual number. Multi-territory firms put
their whole board into every territory they are listed in, which is exactly
the tie being counted: a Paris-registered firm operating in Morocco and
Indochina links the two.</p>

<h2>One figure per territory</h2>
<p class="sub">Each is that territory's complete interlock graph, drawn from
its own bundle in <code>data/by_{level}/</code>. One hue, so no legend: the
heading names the series. Counts under each heading are for that territory
alone.</p>
<div class="toc">{toc}</div>
{empty_note}
<div class="grid">{''.join(cards)}</div>

<div id="tbl" hidden>
  <h2>Territories</h2>
  <table><thead><tr><th>Territory</th><th>Firms</th><th>Interlocks</th>
  <th>Components</th><th>Largest</th></tr></thead><tbody>{rows}</tbody></table>
</div>

<div id="tip" class="tooltip" role="status" aria-live="polite"></div>
<script>
const NODES = {node_json};
const tip = document.getElementById('tip');
function show(e, h) {{
  tip.innerHTML = h; tip.style.opacity = 1;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 10) + 'px';
  tip.style.top  = Math.min(e.clientY + 14, innerHeight - r.height - 10) + 'px';
}}
document.addEventListener('mousemove', e => {{
  const t = e.target;
  if (t.classList && t.classList.contains('nd')) {{
    const d = NODES[t.dataset.id];
    if (d) return show(e, `<b>${{d[0]}}</b><br><span>${{d[1]}}</span><br>` +
      `<span>${{d[2]}} interlocked firms, ${{d[3]}} shared directorships</span>`);
  }}
  if (t.classList && t.classList.contains('mc')) {{
    return show(e, `<b>${{t.dataset.v}} shared directors</b><br>` +
      `<span>${{t.dataset.a}} &middot; ${{t.dataset.b}}</span>`);
  }}
  tip.style.opacity = 0;
}});
const tb = document.getElementById('tbtn'), tbl = document.getElementById('tbl');
tb.onclick = () => {{
  const open = tbl.hidden; tbl.hidden = !open;
  tb.setAttribute('aria-expanded', open);
  tb.textContent = open ? 'Hide data table' : 'Show data table';
}};
document.getElementById('theme').onclick = () => {{
  const cur = document.documentElement.dataset.theme ||
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.theme = cur === 'dark' ? 'light' : 'dark';
}};
</script>
</body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", choices=("country", "region"), default="country")
    ap.add_argument("--min-firms", type=int, default=2,
                    help="skip territories with fewer interlocked firms")
    ap.add_argument("--skip-empire", action="store_true",
                    help="territory figures only (the empire layout is slow)")
    args = ap.parse_args()

    ensure_dir(FIG_DIR)
    out_dir = os.path.join(FIG_DIR, f"by_{args.level}")
    ensure_dir(out_dir)
    companies = {r["company_id"]: r for r in read_csv("companies.csv")}
    lp = PALETTE["light"]

    empire = None
    if not args.skip_empire:
        print("laying out the whole interlock graph (~1 min)...", file=sys.stderr)
        empire = build_empire(companies, EMPIRE_W, EMPIRE_H)
        legend = [(lp["series"][i], t) for i, t in enumerate(empire["top3"])]
        legend.append((lp["other"], "Other territory"))
        path = os.path.join(FIG_DIR, "fig4_empire_network.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg_document(
                empire_svg(empire, "light"), EMPIRE_W, EMPIRE_H, "light",
                "Empire-wide interlock network", legend,
                f"All {empire['n_firms']:,} firms sharing a director, "
                f"{empire['n_edges']:,} interlocks. Giant component "
                f"{empire['n_giant']:,} firms ({empire['n_giant'] / empire['n_firms'] * 100:.1f}%); "
                f"the residue is in the strip below the rule."))
        print(f"wrote {os.path.relpath(path, ROOT)}", file=sys.stderr)

    matrix = build_matrix()
    body, _, total = matrix_svg(matrix, "light")
    path = os.path.join(FIG_DIR, "fig5_territory_matrix.svg")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg_document(
            body, MATRIX_LABEL + len(matrix["territories"]) * CELL + 40, total,
            "light", "Shared directors between territories", None,
            f"{len(matrix['territories'])} territories with eight or more "
            f"directors; the cell is the count sitting on boards in both. "
            f"Shading steps by rank, not linearly: the counts are heavily "
            f"skewed, and a linear ramp leaves everything but the top few "
            f"pairs in the palest step."))
    print(f"wrote {os.path.relpath(path, ROOT)}", file=sys.stderr)

    territories, empty = [], []
    for row in load_manifest(args.level):
        t = build_territory(args.level, row["slug"], row["territory"],
                            TERR_W, None, int(row["n_companies"]))
        if t is None or t["n_firms"] < args.min_firms:
            empty.append(row["territory"])
            continue
        territories.append(t)
        p = os.path.join(out_dir, f"{row['slug']}.svg")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(svg_document(
                territory_svg(t, "light"), TERR_W, t["height"], "light",
                f"{row['territory']} interlock network", None,
                territory_caption(t)))
    territories.sort(key=lambda t: -t["n_edges"])
    print(f"wrote {len(territories)} territory figures to "
          f"{os.path.relpath(out_dir, ROOT)}", file=sys.stderr)

    if empire is not None:
        page = render_gallery(empire, matrix, territories, empty, args.level)
        p = os.path.join(FIG_DIR, "territory_networks.html")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(page)
        print(f"wrote {os.path.relpath(p, ROOT)}", file=sys.stderr)
        print(f"\nempire: {empire['n_firms']:,} firms, {empire['n_edges']:,} "
              f"interlocks, {empire['n_components']} components, "
              f"territories {empire['top3']}", file=sys.stderr)
    print(f"matrix: {len(matrix['territories'])} territories, "
          f"{len(matrix['cells']):,} pairs share a director, max "
          f"{matrix['hi']:,}", file=sys.stderr)
    if empty:
        print(f"no network to draw for {len(empty)}: {', '.join(empty[:6])}"
              f"{'...' if len(empty) > 6 else ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
