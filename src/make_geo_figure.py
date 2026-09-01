"""Stage 10 - the empire's interlock network on the map.

    figures/fig7_city_network.svg      cities in true position, ties between them
    figures/city_network.html          the same, with hover and a table
    data/processed/edges_city_interlock.csv

Every other figure here places firms by a force-directed layout, where
position means "connected to". This one places them by **latitude and
longitude**, so position means where the firm actually was, and the edges then
show which places the same directors sat in.

The unit is the city, not the colony. Filing a firm under *Indochine* hides
that Saigon and Hanoi were substantially separate business worlds; filing it
under *Maroc* hides that most of its board met in Paris. `geocode.py` recovers
the city, and this draws the network over it.

Three things this figure is honest about, because each could mislead:

- **Coverage is partial.** 45% of the firms in the interlock graph have a
  recoverable city. The figure draws those; it is not a map of the empire's
  firms but of the ones whose address survived.
- **A head office is not an operation.** A rubber plantation in Cochinchina
  run from a Paris office appears at Paris. That is what the source records
  and it is a real fact about control, but it is not where the work happened.
- **Ties within a city cannot be drawn** — an edge from Paris to Paris is a
  dot. They are the largest single category and are reported as a number
  instead of being quietly dropped.

The basemap is Natural Earth's 1:50 M coastline, built once into
`data/reference/world_land.geojson` by `fetch_basemap.py` and shared with the
firm-level maps of stage 21, so the two agree about where land is. Land only —
a modern border drawn across a corpus that runs from the 1870s to the 1970s
would be an anachronism. The projection is Robinson, which is what `basemap.py`
gives every map in the repository.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import basemap as BM  # noqa: E402
from common import ensure_dir  # noqa: E402
from labels import LANGS, localise  # noqa: E402
from make_figures import (  # noqa: E402
    FIG_DIR, PALETTE, ROOT, build_interlock_graph, esc, radius, svg_document,
    trim_to_width, _text_width,
)

W = 1560.0
PAD = 46.0
LAT_MIN, LAT_MAX = -54.0, 70.0   # the same window as stage 21, so the two agree
BOW = 0.09              # of the chord: how far an edge bends off the straight
EDGES_OUT = os.path.join(ROOT, "data", "processed", "edges_city_interlock.csv")

# Three slots, which is the all-pairs cap for a node-link form. The split is
# the analytical one for this figure: where the empire was administered from,
# where it operated, and where it did business outside French sovereignty.
GROUPS = [
    ("metropole", "Metropolitan France"),
    ("empire", "French Empire"),
    ("foreign", "Outside French rule"),
]
GROUP_FR = {"metropole": "France métropolitaine", "empire": "Empire français",
            "foreign": "Hors souveraineté française"}


def load_places() -> dict[str, dict]:
    path = os.path.join(ROOT, "data", "processed", "company_places.csv")
    if not os.path.exists(path):
        raise SystemExit("run: python3 src/geocode.py")
    with open(path, encoding="utf-8", newline="") as fh:
        return {r["company_id"]: r for r in csv.DictReader(fh)}


def build(min_weight: int = 1):
    """Aggregate the firm-level interlock graph up to cities."""
    places = load_places()
    G = build_interlock_graph(min_weight)

    city_firms: dict[str, list[str]] = defaultdict(list)
    for n in G.nodes():
        rec = places.get(n)
        if rec and rec["city"]:
            city_firms[rec["city"]].append(n)

    between: Counter = Counter()
    within: Counter = Counter()
    for a, b, d in G.edges(data=True):
        ca = places.get(a, {}).get("city")
        cb = places.get(b, {}).get("city")
        if not ca or not cb:
            continue
        if ca == cb:
            within[ca] += 1
        else:
            between[tuple(sorted((ca, cb)))] += 1

    meta = {}
    for city, firms in city_firms.items():
        rec = places[firms[0]]
        meta[city] = {"lat": float(rec["lat"]), "lon": float(rec["lon"]),
                      "territory": rec["city_territory"], "group": rec["group"],
                      "n_firms": len(firms), "within": within.get(city, 0)}
    n_placed = sum(len(f) for f in city_firms.values())
    return meta, between, {
        "n_graph": G.number_of_nodes(),
        "n_placed": n_placed,
        "n_edges_graph": G.number_of_edges(),
        "n_between": sum(between.values()),
        "n_within": sum(within.values()),
        "n_cities": len(meta),
    }


def project(meta, width, pad):
    """Robinson, from `basemap.py`, on the window every map in the repo uses.

    The first version of this figure derived the canvas from the data's own
    latitude span under plate carrée. That made the figure's geometry a
    function of which firms happened to have an address, so adding one firm in
    Reykjavik would have restretched the whole map — and it could not be
    compared with the firm-level maps of stage 21. A fixed projection and a
    fixed window fix both.
    """
    proj = BM.Robinson(width, pad=pad, lat_min=LAT_MIN, lat_max=LAT_MAX)
    pos = {c: proj.project(m["lat"], m["lon"]) for c, m in meta.items()}
    return pos, proj, proj.height


def place_labels(nodes, font, width, height, top):
    """Direct labels with a greedy four-way search.

    A map has ocean in it, so labels go beside their city rather than in a
    margin column: a leader line across the Atlantic to a stacked list would
    destroy the one thing this figure has that the others do not, which is
    that position means something.
    """
    ranked = sorted(nodes, key=lambda n: -n["n_firms"])[:top]
    taken: list[tuple[float, float, float, float]] = []

    def free(box):
        x0, y0, x1, y1 = box
        if x0 < 2 or x1 > width - 2 or y0 < 2 or y1 > height - 2:
            return False
        return not any(x0 < b[2] and b[0] < x1 and y0 < b[3] and b[1] < y1
                       for b in taken)

    out = []
    for n in ranked:
        text = trim_to_width(n["label"], font, 150)
        tw, th = _text_width(text, font), font * 1.15
        r = n["r"]
        for dx, dy, anchor in ((r + 5, font * 0.36, "start"),
                               (-r - 5, font * 0.36, "end"),
                               (0, -r - 5, "middle"),
                               (0, r + th, "middle")):
            x, y = n["x"] + dx, n["y"] + dy
            x0 = x if anchor == "start" else (x - tw if anchor == "end" else x - tw / 2)
            box = (x0 - 2, y - th, x0 + tw + 2, y + 3)
            if free(box):
                taken.append(box)
                out.append((x, y, anchor, text))
                break
    return out


def draw(meta, between, pos, proj, height, mode, lang, label_top=34):
    p = PALETTE[mode]
    slot = {g: i for i, (g, _) in enumerate(GROUPS)}
    wmax = max(between.values()) if between else 1
    fmax = max(m["n_firms"] for m in meta.values())
    fmin = min(m["n_firms"] for m in meta.values())

    # The id carries the mode: the HTML page embeds the light and the dark
    # body in one document, and two clip paths called clip7 is one clip path.
    out = [BM.basemap_svg(proj, p, f"clip7_{mode}")]
    out.append(f'<g stroke="{p["edge"]}" fill="none">')
    for (a, b), w in sorted(between.items(), key=lambda kv: kv[1]):
        (x1, y1), (x2, y2) = pos[a], pos[b]
        t = w / wmax
        # Bowed, always to the same side of a→b, and for the same reason as on
        # the firm-level maps: straight lines sharing a corridor — and almost
        # every corridor here starts in Paris — collapse into one grey smear.
        dx, dy = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) / 2 - dy * BOW, (y1 + y2) / 2 + dx * BOW
        out.append(
            f'<path d="M{x1:.1f} {y1:.1f}Q{cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}" '
            f'stroke-width="{0.5 + 3.4 * math.sqrt(t):.2f}" '
            f'stroke-opacity="{0.14 + 0.55 * math.sqrt(t):.3f}"/>')
    out.append("</g>")

    nodes = []
    for city, m in meta.items():
        nodes.append({
            "id": city, "label": city, "x": pos[city][0], "y": pos[city][1],
            "r": radius(m["n_firms"], fmin, fmax),
            "n_firms": m["n_firms"], "within": m["within"],
            "group": m["group"], "territory": m["territory"],
            "color": p["series"][slot.get(m["group"], 0)],
        })
    out.append("<g>")
    for n in sorted(nodes, key=lambda n: n["r"]):
        out.append(
            f'<circle class="nd" data-id="{esc(n["id"])}" cx="{n["x"]:.1f}" '
            f'cy="{n["y"]:.1f}" r="{n["r"]:.2f}" fill="{n["color"]}" '
            f'stroke="{p["surface"]}" stroke-width="1.6"/>')
    out.append("</g>")

    out.append(f'<g font-size="11" font-family="ui-sans-serif,system-ui,sans-serif" '
               f'fill="{p["text_primary"]}">')
    for x, y, anchor, text in place_labels(nodes, 11.0, W, height, label_top):
        # A halo, so a label crossing an edge stays readable without a box.
        out.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'stroke="{p["surface"]}" stroke-width="2.6" stroke-linejoin="round" '
            f'paint-order="stroke">{esc(text)}</text>')
    out.append("</g>")
    return "\n".join(out), nodes


def legend_for(lang):
    return [(PALETTE["light"]["series"][i],
             label if lang == "en" else GROUP_FR[key])
            for i, (key, label) in enumerate(GROUPS)]


def write_edges(between, meta):
    with open(EDGES_OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["city_1", "city_2", "territory_1", "territory_2",
                    "group_1", "group_2", "n_interlocks"])
        for (a, b), n in sorted(between.items(), key=lambda kv: -kv[1]):
            w.writerow([a, b, meta[a]["territory"], meta[b]["territory"],
                        meta[a]["group"], meta[b]["group"], n])
    print(f"wrote {os.path.relpath(EDGES_OUT, ROOT)}: {len(between):,} city pairs",
          file=sys.stderr)


def render_page(nodes, stats, body_light, body_dark, lang, height) -> str:
    lp, dp = PALETTE["light"], PALETTE["dark"]
    legend = "".join(
        f'<span class="lg" role="listitem"><i style="background:var(--s{i + 1})"></i>'
        f'{esc(label if lang == "en" else GROUP_FR[key])}</span>'
        for i, (key, label) in enumerate(GROUPS))
    node_json = json.dumps({n["id"]: [n["label"], localise(n["territory"], lang),
                                      n["n_firms"], n["within"]] for n in nodes})
    rows = "".join(
        f"<tr><td>{esc(n['label'])}</td>"
        f"<td>{esc(localise(n['territory'], lang))}</td>"
        f"<td class='n'>{n['n_firms']:,}</td><td class='n'>{n['within']:,}</td></tr>"
        for n in sorted(nodes, key=lambda n: -n["n_firms"]))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Where the empire's boards met</title>
<style>
  :root {{
    --surface:{lp['surface']}; --text-primary:{lp['text_primary']};
    --text-secondary:{lp['text_secondary']}; --text-muted:{lp['text_muted']};
    --hairline:{lp['hairline']}; --s1:{lp['series'][0]}; --s2:{lp['series'][1]};
    --s3:{lp['series'][2]};
  }}
  html[data-theme="dark"] {{
    --surface:{dp['surface']}; --text-primary:{dp['text_primary']};
    --text-secondary:{dp['text_secondary']}; --text-muted:{dp['text_muted']};
    --hairline:{dp['hairline']}; --s1:{dp['series'][0]}; --s2:{dp['series'][1]};
    --s3:{dp['series'][2]};
  }}
  @media (prefers-color-scheme: dark) {{
    html:not([data-theme="light"]) {{
      --surface:{dp['surface']}; --text-primary:{dp['text_primary']};
      --text-secondary:{dp['text_secondary']}; --text-muted:{dp['text_muted']};
      --hairline:{dp['hairline']}; --s1:{dp['series'][0]}; --s2:{dp['series'][1]};
      --s3:{dp['series'][2]};
    }}
    html:not([data-theme="light"]) .light-only {{ display:none; }}
    html:not([data-theme="light"]) .dark-only {{ display:block; }}
  }}
  .dark-only {{ display:none; }}
  html[data-theme="dark"] .light-only {{ display:none; }}
  html[data-theme="dark"] .dark-only {{ display:block; }}
  html[data-theme="light"] .light-only {{ display:block; }}
  html[data-theme="light"] .dark-only {{ display:none; }}
  body {{ margin:0; padding:34px 30px 80px; background:var(--surface);
    color:var(--text-primary); font:15px/1.55 ui-sans-serif,system-ui,sans-serif;
    max-width:1620px; }}
  h1 {{ font-size:27px; letter-spacing:-.01em; margin:0 0 6px; }}
  h2 {{ font-size:19px; margin:44px 0 4px; }}
  p.sub {{ color:var(--text-secondary); margin:0 0 14px; max-width:80ch; }}
  p.note {{ color:var(--text-muted); font-size:13px; margin:10px 0 0; max-width:86ch; }}
  .bar {{ display:flex; align-items:center; gap:16px; flex-wrap:wrap; margin:0 0 10px; }}
  .legend {{ display:inline-flex; align-items:center; gap:16px; flex-wrap:wrap; }}
  .lg {{ display:inline-flex; align-items:center; gap:7px; font-size:13px;
    color:var(--text-secondary); }}
  .lg i {{ width:11px; height:11px; border-radius:50%; display:inline-block; }}
  button {{ font:inherit; font-size:13px; padding:5px 11px; border-radius:7px;
    border:1px solid var(--hairline); background:transparent;
    color:var(--text-secondary); cursor:pointer; }}
  .fig {{ overflow-x:auto; border:1px solid var(--hairline); border-radius:8px; }}
  .fig svg {{ display:block; max-width:100%; height:auto; }}
  table {{ border-collapse:collapse; font-size:13px; margin-top:12px; }}
  th,td {{ text-align:left; padding:4px 16px 4px 0;
    border-bottom:1px solid var(--hairline); }}
  th {{ color:var(--text-secondary); font-weight:600; }}
  td.n, th.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .tooltip {{ position:fixed; pointer-events:none; opacity:0; transition:opacity .1s;
    background:var(--surface); border:1px solid var(--hairline); border-radius:8px;
    padding:7px 10px; font-size:12.5px; box-shadow:0 4px 16px rgba(0,0,0,.13);
    max-width:280px; z-index:9; }}
  .tooltip b {{ font-weight:620; }} .tooltip span {{ color:var(--text-secondary); }}
  .nd:hover {{ stroke:var(--text-primary); stroke-width:1.6; }}
</style></head>
<body class="viz-root">
<h1>Where the empire's boards met</h1>
<p class="sub">Every other figure in this repository places a firm by whom it
is connected to. This one places it by <b>where it was</b> — city coordinates
on a Robinson projection — and draws an edge between two cities when a director sat on a
board in each. The unit is the city rather than the colony, because filing a
firm under <i>Indochine</i> hides that Saigon and Hanoi were largely separate
business worlds, and filing it under <i>Maroc</i> hides that its board met in
Paris.</p>

<div class="bar">
  <span class="legend" role="list" aria-label="Legend: sovereignty">{legend}</span>
  <button id="tbtn" aria-expanded="false">Show data table</button>
  <button id="theme">Toggle dark mode</button>
</div>
<div class="fig">
  <div class="light-only">{svg_document(body_light, W, height, 'light', "Interlock network by city")}</div>
  <div class="dark-only">{svg_document(body_dark, W, height, 'dark', "Interlock network by city")}</div>
</div>
<p class="note"><b>Paris is the finding, not an artefact.</b>
{stats['paris_share']:.0f}% of the placed firms in the interlock graph were run
from Paris — more than the next {stats['paris_beats']} cities together — and
the densest lines on the map run from Paris outward rather than between
colonies. Colonial business was administered from the metropole.</p>
<p class="note">Read with three limits in mind. <b>Coverage is partial:</b>
{stats['n_placed']:,} of the {stats['n_graph']:,} firms in the interlock graph
have a recoverable address ({100 * stats['n_placed'] / stats['n_graph']:.0f}%),
and the rest are absent from this figure entirely. <b>A head office is not an
operation:</b> a plantation in Cochinchina run from a Paris office appears at
Paris, which is a real fact about control but not about where the work
happened. <b>Ties within one city cannot be drawn</b> — an edge from Paris to
Paris is a dot — so the {stats['n_within']:,} within-city interlocks are in the
table's last column, not on the map, against {stats['n_between']:,} drawn
between cities. There is no coastline because no basemap ships with this
repository; the graticule and the labels carry the geography.</p>

<div id="tbl" hidden>
  <h2>Cities</h2>
  <table><thead><tr><th>City</th><th>Territory</th>
  <th class="n">Firms</th><th class="n">Ties within the city</th></tr></thead>
  <tbody>{rows}</tbody></table>
</div>

<div id="tip" class="tooltip" role="status" aria-live="polite"></div>
<script>
const C = {node_json};
const tip = document.getElementById('tip');
document.addEventListener('mousemove', e => {{
  const t = e.target;
  if (t.classList && t.classList.contains('nd') && C[t.dataset.id]) {{
    const d = C[t.dataset.id];
    tip.innerHTML = `<b>${{d[0]}}</b><br><span>${{d[1]}}</span><br>` +
      `<span>${{d[2]}} firms &middot; ${{d[3]}} ties inside the city</span>`;
    tip.style.opacity = 1;
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 10) + 'px';
    tip.style.top = Math.min(e.clientY + 14, innerHeight - r.height - 10) + 'px';
    return;
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
    ap.add_argument("--min-weight", type=int, default=1)
    ap.add_argument("--label-top", type=int, default=34)
    ap.add_argument("--lang", choices=LANGS, default="fr")
    args = ap.parse_args()

    meta, between, stats = build(args.min_weight)
    if not meta:
        raise SystemExit("no placed firms; run python3 src/geocode.py first")
    write_edges(between, meta)

    pos, proj, height = project(meta, W, PAD)
    body_light, nodes = draw(meta, between, pos, proj, height, "light", args.lang,
                             args.label_top)
    body_dark, _ = draw(meta, between, pos, proj, height, "dark", args.lang,
                        args.label_top)

    ranked = sorted(meta.items(), key=lambda kv: -kv[1]["n_firms"])
    paris = dict(ranked).get("Paris", {}).get("n_firms", 0)
    run = 0
    beats = 0
    for city, m in ranked[1:]:
        run += m["n_firms"]
        beats += 1
        if run >= paris:
            break
    stats["paris_share"] = 100 * paris / stats["n_placed"]
    stats["paris_beats"] = beats

    base = FIG_DIR if args.lang == "fr" else os.path.join(FIG_DIR, "en")
    ensure_dir(base)
    path = os.path.join(base, "fig7_city_network.svg")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg_document(
            body_light, W, height, "light", "Interlock network by city",
            legend_for(args.lang),
            f"{stats['n_cities']} cities holding {stats['n_placed']:,} of the "
            f"{stats['n_graph']:,} firms in the interlock graph "
            f"({100 * stats['n_placed'] / stats['n_graph']:.0f}% have a recoverable "
            f"address). Node area is firms based there; line weight is interlocks "
            f"between the two cities. {stats['n_within']:,} further ties fall "
            f"within a single city and cannot be drawn as edges. Robinson "
            f"projection; coastline from Natural Earth 1:50 M, land only."))
    print(f"wrote {os.path.relpath(path, ROOT)}", file=sys.stderr)

    page = render_page(nodes, stats, body_light, body_dark, args.lang, height)
    ppath = os.path.join(base, "city_network.html")
    with open(ppath, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {os.path.relpath(ppath, ROOT)}", file=sys.stderr)

    print(f"\n{stats['n_cities']} cities, {stats['n_placed']:,}/{stats['n_graph']:,} "
          f"firms placed, {stats['n_between']:,} between-city ties, "
          f"{stats['n_within']:,} within-city", file=sys.stderr)
    print(f"Paris holds {stats['paris_share']:.0f}% of placed firms "
          f"(more than the next {stats['paris_beats']} cities combined)",
          file=sys.stderr)
    for city, m in ranked[:8]:
        print(f"  {m['n_firms']:5d}  {city}", file=sys.stderr)


if __name__ == "__main__":
    main()
