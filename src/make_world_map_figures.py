"""Stage 21 - the whole interlock network, drawn on the world map.

    python3 src/make_world_map_figures.py
    python3 src/make_world_map_figures.py --lang en

Figure 7 maps **cities**: it collapses each city to one node, so Paris is one
dot and the ties inside a city are a number in the table rather than lines on
the map. These four figures map **firms**. Every firm the placement ladder of
stage 20 could place gets its own coordinate, spread deterministically inside a
disc around its anchor so that co-located firms do not overprint — which is
what makes the 9,025 ties *within* a single place drawable for the first time.

- **fig53, the network on the map.** All 3,910 placed firms and all 43,164
  drawable ties. Colour is the *rung of the placement ladder*, not geography,
  because position already carries geography and the one thing a reader must
  know is that 1,896 of these firms sit at a filing-category anchor rather than
  an address.
- **fig54, with Paris and without it.** The same coordinates twice: the ties
  that touch Paris, then the ties that do not. Paris holds 19.5% of the placed
  firms and touches 63.7% of the drawable ties.
- **fig55, the geography of a tie.** The drawable ties classified, with the
  share that never leave one place drawn inside the bar.
- **fig56, where the banks were.** Finance on the map, with only its own ties.

**All four figures share one set of coordinates.** A firm is at the same point
in every panel it appears in, so a difference between panels is a difference in
the data.

Three limits, restated on each figure because each could mislead:

- **Coverage is 65%.** 2,079 firms have neither an address nor a single filing
  country, and their 35,908 ties are not on the map. They are not a random
  sample: the transversal firms are among the largest in the corpus.
- **A territory anchor is not an address.** It is the mean of that territory's
  gazetteer cities, and a firm placed there might have been run from Paris.
- **A head office is not an operation.** A Cochinchina plantation directed
  from Paris appears at Paris, which is a real fact about control and not
  about where the work happened.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import draw  # noqa: E402
from common import ensure_dir  # noqa: E402
from labels import LANGS, localise  # noqa: E402
from make_descriptive_figures import PAGE_CSS, _axis_text, _table_html  # noqa: E402
from make_figures import (FIG_DIR, PALETTE, build_interlock_graph,  # noqa: E402
                          esc, svg_document, trim_to_width, _text_width)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")

W = 1560.0
PAD = 44.0
MAP_H = 560.0           # target height for one map panel, before the aspect fit
SPREAD = 2.35           # px per firm-slot inside an anchor disc; sets disc area
NODE_R = 1.25
GOLDEN = 2.399963229728653   # radians; the sunflower angle
EDGE_BANDS = 3          # weight bands, one <path> each — see _edge_paths


def load(name):
    path = os.path.join(PROC, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _disc(n: int, cx: float, cy: float, r: float):
    """`n` points spread through a disc of radius `r`, golden-angle order.

    Radius goes as sqrt of the index so the points are uniform by *area*
    rather than piling up at the centre; the angle is the sunflower angle and
    means nothing beyond spreading them apart. Deterministic, so a firm keeps
    its pixel across figures and across reruns.
    """
    if n == 1:
        return [(cx, cy)]
    out = []
    for i in range(n):
        rad = r * math.sqrt((i + 0.5) / n)
        ang = i * GOLDEN
        out.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return out


def gather() -> dict:
    rows = load("company_map_positions.csv")
    if not rows:
        raise SystemExit("run: python3 src/place_on_map.py")
    placed = [r for r in rows if r["lat"]]
    G = build_interlock_graph(1)

    # Anchors first, so the projection is fitted to the anchors and the discs
    # are hung off it.
    anchors: dict[str, dict] = {}
    for r in placed:
        a = anchors.setdefault(r["anchor"], {
            "anchor": r["anchor"], "lat": float(r["lat"]),
            "lon": float(r["lon"]), "group": r["group"],
            "territory": r["anchor_territory"], "level": r["placement_level"],
            "firms": [],
        })
        a["firms"].append(r["company_id"])

    lats = [a["lat"] for a in anchors.values()]
    lons = [a["lon"] for a in anchors.values()]
    lat0, lat1 = min(lats), max(lats)
    lon0, lon1 = min(lons), max(lons)
    s = (W - 2 * PAD) / max(lon1 - lon0, 1e-6)
    height = (lat1 - lat0) * s + 2 * PAD
    box = (lat0, lat1, lon0, lon1, s, PAD, PAD)

    def to_px(lat, lon):
        return PAD + (lon - lon0) * s, PAD + (lat1 - lat) * s

    pos: dict[str, tuple[float, float]] = {}
    for a in anchors.values():
        cx, cy = to_px(a["lat"], a["lon"])
        a["x"], a["y"] = cx, cy
        n = len(a["firms"])
        a["r"] = SPREAD * math.sqrt(n / math.pi) if n > 1 else 0.0
        for cid, xy in zip(sorted(a["firms"]), _disc(n, cx, cy, a["r"])):
            pos[cid] = xy

    by_id = {r["company_id"]: r for r in rows}
    edges = [(a, b, d.get("weight", 1)) for a, b, d in G.edges(data=True)
             if a in pos and b in pos]
    return {
        "rows": rows, "by_id": by_id, "anchors": anchors, "pos": pos,
        "box": box, "height": height, "G": G, "edges": edges,
        "ties": load("map_tie_geography.csv"),
        "base": (load("map_geography_baseline.csv") or [{}])[0],
    }


def graticule(box, mode, height, y0=0.0):
    """A lat/lon grid: no basemap ships with this repo, so this is the geography."""
    lat0, lat1, lon0, lon1, s, ox, oy = box
    p = PALETTE[mode]
    out = [f'<g stroke="{p["hairline"]}" stroke-width="0.8" fill="none">']
    labels = []
    for lon in range(int(math.floor(lon0 / 30) * 30), int(lon1) + 31, 30):
        x = ox + (lon - lon0) * s
        if -2 <= x <= W + 2:
            out.append(f'<line x1="{x:.1f}" y1="{y0:.1f}" x2="{x:.1f}" '
                       f'y2="{y0 + height:.1f}"/>')
            labels.append((x, y0 + height - 6,
                           f"{abs(lon)}°{'E' if lon > 0 else ('W' if lon < 0 else '')}"))
    for lat in range(int(math.floor(lat0 / 20) * 20), int(lat1) + 21, 20):
        y = y0 + oy + (lat1 - lat) * s
        if y0 - 2 <= y <= y0 + height + 2:
            out.append(f'<line x1="0" y1="{y:.1f}" x2="{W:.0f}" y2="{y:.1f}"/>')
            labels.append((4, y - 4,
                           f"{abs(lat)}°{'N' if lat > 0 else ('S' if lat < 0 else '')}"))
    out.append("</g>")
    out.append(f'<g font-size="9.5" font-family="ui-sans-serif,system-ui,sans-serif" '
               f'fill="{p["text_muted"]}">')
    for x, y, t in labels:
        out.append(f'<text x="{x + 3:.1f}" y="{y:.1f}">{t}</text>')
    out.append("</g>")
    return "".join(out)


def _edge_paths(edges, pos, mode, dy=0.0, base_op=0.055):
    """Every edge, as `EDGE_BANDS` paths instead of tens of thousands of lines.

    43,164 `<line>` elements with their own stroke attributes is a four-megabyte
    file that no browser enjoys. Bucketing by interlock weight and emitting one
    path per bucket gives the same picture in a tenth of the bytes, and the
    three buckets carry the weight the per-line widths used to.
    """
    if not edges:
        return ""
    p = PALETTE[mode]
    hi = max(w for _, _, w in edges)
    bands: list[list[str]] = [[] for _ in range(EDGE_BANDS)]
    for a, b, w in edges:
        i = min(EDGE_BANDS - 1, int(EDGE_BANDS * math.sqrt((w - 1) / max(hi - 1, 1))))
        (x1, y1), (x2, y2) = pos[a], pos[b]
        bands[i].append(f"M{x1:.1f} {y1 + dy:.1f}L{x2:.1f} {y2 + dy:.1f}")
    out = []
    for i, segs in enumerate(bands):
        if not segs:
            continue
        out.append(f'<path d="{"".join(segs)}" fill="none" stroke="{p["edge"]}" '
                   f'stroke-width="{0.3 + 0.5 * i:.2f}" '
                   f'stroke-opacity="{min(0.72, base_op * (1 + 1.9 * i)):.3f}"/>')
    return "".join(out)


def _nodes(ids, d, mode, colour_of, dy=0.0, r=NODE_R, radius_of=None):
    by_colour: dict[str, list[str]] = defaultdict(list)
    # Largest anchor first, so the dots of a small place that a big neighbour's
    # disc engulfs — Brussels inside Paris — are painted on top of it.
    order = sorted(ids, key=lambda cid: -len(
        d["anchors"][d["by_id"][cid]["anchor"]]["firms"]))
    for cid in order:
        x, y = d["pos"][cid]
        rr = radius_of(cid) if radius_of else r
        by_colour[colour_of(cid)].append(f'<circle cx="{x:.1f}" cy="{y + dy:.1f}" '
                                         f'r="{rr:.2f}"/>')
    # One <g> per colour, so the fill is written once rather than 3,910 times.
    return "".join(f'<g fill="{c}">{"".join(v)}</g>'
                   for c, v in sorted(by_colour.items(), key=lambda kv: -len(kv[1])))


def _discs(d, mode, dy=0.0, min_firms=15):
    """A hairline ring at each big anchor's edge.

    Where two places are close and one is large, its disc swallows the other:
    Brussels, Lyon and Marseille all fall inside Paris's 762-firm disc. The
    ring says where each disc ends, so a label pinned to an edge has a visible
    edge to be pinned to.
    """
    p = PALETTE[mode]
    out = []
    for a in sorted(d["anchors"].values(), key=lambda a: -len(a["firms"])):
        if len(a["firms"]) < min_firms:
            continue
        out.append(f'<circle cx="{a["x"]:.1f}" cy="{a["y"] + dy:.1f}" '
                   f'r="{a["r"] + 1.6:.1f}"/>')
    if not out:
        return ""
    return (f'<g fill="none" stroke="{p["hairline"]}" stroke-width="1.1">'
            f'{"".join(out)}</g>')


def _anchor_labels(d, mode, top, dy=0.0, height=None):
    """Direct labels for the biggest anchors, placed outward from the disc.

    A map has ocean in it, so a label goes beside its anchor rather than in a
    margin column: a leader line across the Atlantic to a stacked list would
    destroy the one thing this figure has, which is that position means
    something.
    """
    p = PALETTE[mode]
    ranked = sorted(d["anchors"].values(), key=lambda a: -len(a["firms"]))[:top]
    taken: list[tuple[float, float, float, float]] = []
    lim = height if height is not None else d["height"]
    font = 11.0
    out = []

    def free(box):
        if box[0] < 2 or box[2] > W - 2 or box[1] < dy + 2 or box[3] > dy + lim - 2:
            return False
        return not any(box[0] < t[2] and t[0] < box[2] and box[1] < t[3]
                       and t[1] < box[3] for t in taken)

    for rank, a in enumerate(ranked):
        text = trim_to_width(f"{a['anchor']} {len(a['firms']):,}", font, 250)
        tw, th = _text_width(text, font), font * 1.15
        rr = max(a["r"], 2.0) + 4
        for dx, dyy, anch in ((rr, font * 0.36, "start"), (-rr, font * 0.36, "end"),
                              (0, -rr, "middle"), (0, rr + th * 0.8, "middle")):
            x, y = a["x"] + dx, a["y"] + dy + dyy
            x0 = x if anch == "start" else (x - tw if anch == "end" else x - tw / 2)
            box = (x0 - 2, y - th, x0 + tw + 2, y + 3)
            if free(box):
                taken.append(box)
                out.append(draw.halo_text(
                    mode, x, y, text, anch, font=font,
                    weight="600" if rank < 3 else "400",
                    fill=p["text_primary"]))
                break
    return "".join(out)


LEVEL_LABEL = {
    "fr": {"city": "placée par son adresse",
           "territory": "placée par son pays de classement"},
    "en": {"city": "placed by its address",
           "territory": "placed by its filing country"},
}


# --- fig53: the full network on the map -----------------------------------
def fig_full_map(d, mode, lang):
    p = PALETTE[mode]
    b = d["base"]
    h = d["height"]
    lvl = {cid: d["by_id"][cid]["placement_level"] for cid in d["pos"]}
    colour = {"city": p["series"][0], "territory": p["series"][1]}

    body = [graticule(d["box"], mode, h),
            _edge_paths(d["edges"], d["pos"], mode),
            _discs(d, mode),
            _nodes(d["pos"], d, mode, lambda cid: colour[lvl[cid]]),
            _anchor_labels(d, mode, 30)]

    n_city = int(b["n_placed_city"])
    n_terr = int(b["n_placed_territory"])
    placed = n_city + n_terr
    title = {"fr": "Le réseau d'interconnexions sur la carte du monde",
             "en": "The interlock network on the world map"}[lang]
    caption = {
        "fr": (f"Les {placed:,} entreprises que la source permet de situer, chacune "
               f"à son propre point, et les {int(b['n_drawable_edges']):,} liens entre "
               f"elles — dont {int(b['n_same_anchor_edges']):,} qui ne quittent pas un "
               f"seul lieu et qu'une carte par ville ne peut pas tracer. L'aire du "
               f"disque est proportionnelle au nombre d'entreprises ; la position dans "
               f"le disque ne signifie rien. La couleur est le degré de précision : "
               f"{n_terr:,} entreprises n'ont pas d'adresse et sont placées au point "
               f"d'ancrage de leur pays de classement. Les disques se chevauchent "
               f"là où deux lieux sont proches — un anneau marque le bord de "
               f"chacun. {int(b['n_unplaced']):,} "
               f"entreprises et leurs liens ne sont pas sur la carte. Projection "
               f"plate carrée ; pas de fond de carte, la graticule porte la géographie."),
        "en": (f"The {placed:,} firms the source can place, each at its own point, and "
               f"the {int(b['n_drawable_edges']):,} ties among them — "
               f"{int(b['n_same_anchor_edges']):,} of which never leave a single place "
               f"and cannot be drawn at all on a map of cities. Disc area is "
               f"proportional to the firms in it; position inside a disc means nothing. "
               f"Colour is precision, not geography: {n_terr:,} of these firms have no "
               f"address and sit at their filing country's anchor point, which is a "
               f"fact about the catalogue. Discs overlap where two places are close, "
               f"so a hairline ring marks the edge of each. "
               f"{int(b['n_unplaced']):,} firms and their ties "
               f"are not on this map. Plate carrée; no basemap ships with this repo, so "
               f"the graticule carries the geography."),
    }[lang]
    legend = [(colour["city"], f"{LEVEL_LABEL[lang]['city']} ({n_city:,})"),
              (colour["territory"], f"{LEVEL_LABEL[lang]['territory']} ({n_terr:,})")]
    table = _anchor_table(d, lang)
    return "".join(body), h, title, legend, caption, table


def _anchor_table(d, lang, top=40):
    head = {"fr": ["Lieu", "Territoire", "Entreprises", "Liens internes"],
            "en": ["Place", "Territory", "Firms", "Ties within"]}[lang]
    within: Counter = Counter()
    for a, bb, _w in d["edges"]:
        aa, ab = d["by_id"][a]["anchor"], d["by_id"][bb]["anchor"]
        if aa == ab:
            within[aa] += 1
    rows = []
    for a in sorted(d["anchors"].values(), key=lambda a: -len(a["firms"]))[:top]:
        rows.append([a["anchor"], localise(a["territory"], lang, "territory"),
                     f"{len(a['firms']):,}", f"{within[a['anchor']]:,}"])
    return head, rows


# --- fig54: with Paris, and without it ------------------------------------
def fig_paris(d, mode, lang):
    p = PALETTE[mode]
    b = d["base"]
    h = d["height"]
    gap = 30.0
    paris = {cid for cid in d["pos"] if d["by_id"][cid]["anchor"] == "Paris"}
    touch = [(a, bb, w) for a, bb, w in d["edges"] if a in paris or bb in paris]
    rest = [(a, bb, w) for a, bb, w in d["edges"] if a not in paris and bb not in paris]

    def colour_of(cid):
        return p["series"][0] if cid in paris else p["other"]

    panels = {"fr": ["Les liens qui passent par Paris",
                     "Les liens qui ne passent pas par Paris"],
              "en": ["Ties that touch Paris", "Ties that do not"]}[lang]
    body = []
    for i, (edges, label) in enumerate(zip((touch, rest), panels)):
        dy = i * (h + gap)
        body.append(graticule(d["box"], mode, h, dy))
        body.append(_edge_paths(edges, d["pos"], mode, dy, base_op=0.07))
        body.append(_discs(d, mode, dy))
        body.append(_nodes(d["pos"], d, mode, colour_of, dy))
        body.append(_anchor_labels(d, mode, 18 if i else 14, dy, h))
        body.append(draw.halo_text(mode, 10, dy + 20,
                                   f"{label} — {len(edges):,}", "start",
                                   font=13.0, weight="600"))
    total = 2 * h + gap

    share = 100 * len(touch) / max(len(d["edges"]), 1)
    pshare = 100 * len(paris) / max(int(b["n_placed_city"]) + int(b["n_placed_territory"]), 1)
    title = {"fr": "Le réseau avec Paris, puis sans Paris",
             "en": "The network with Paris, then without it"}[lang]
    caption = {
        "fr": (f"Les mêmes coordonnées deux fois ; seuls les liens changent. Paris "
               f"compte {len(paris):,} entreprises placées, soit {pshare:.1f} % du "
               f"total, et touche {len(touch):,} des {len(d['edges']):,} liens "
               f"traçables ({share:.1f} %). Le second panneau est ce qui reste : "
               f"{len(rest):,} liens, dont la forme est un maillage entre colonies et "
               f"non un moyeu. Attention au biais de couverture — une entreprise sans "
               f"adresse est placée à son pays de classement, ce qui déplace vers les "
               f"colonies des liens qui étaient peut-être parisiens."),
        "en": (f"One set of coordinates, drawn twice; only the ties differ. Paris holds "
               f"{len(paris):,} placed firms, {pshare:.1f}% of them, and touches "
               f"{len(touch):,} of the {len(d['edges']):,} drawable ties ({share:.1f}%). "
               f"The second panel is what is left: {len(rest):,} ties, and its shape is "
               f"a lattice between colonies rather than a hub. Read it against the "
               f"coverage bias — a firm with no address is placed at its filing country, "
               f"which moves ties that may have been Parisian out into the colonies."),
    }[lang]
    legend = [(p["series"][0], "Paris"),
              (p["other"], {"fr": "ailleurs", "en": "elsewhere"}[lang])]
    return "".join(body), total, title, legend, caption, None


# --- fig55: the geography of a tie ---------------------------------------
CLASS_LABEL = {
    "fr": {"colony only": "colonie – colonie",
           "metropole-colony": "métropole – colonie",
           "metropole only": "métropole – métropole",
           "with foreign": "avec l'étranger"},
    "en": {"colony only": "colony – colony",
           "metropole-colony": "metropole – colony",
           "metropole only": "metropole – metropole",
           "with foreign": "with a foreign country"},
}


def fig_tie_geography(d, mode, lang):
    p = PALETTE[mode]
    rows = [r for r in d["ties"] if r["tie_class"] != "unplaced"]
    if not rows:
        return "", 40.0, "", None, "", None
    rows.sort(key=lambda r: -int(r["n_edges"]))
    b = d["base"]

    left, right = 208.0, 150.0
    top, bar, gapy = 34.0, 26.0, 20.0
    hi = max(int(r["n_edges"]) for r in rows)
    span = W - left - right
    body = []
    for i, r in enumerate(rows):
        y = top + i * (bar + gapy)
        n = int(r["n_edges"])
        same = int(r["n_same_anchor"])
        wtot = span * n / hi
        wsame = span * same / hi
        body.append(_axis_text(mode, left - 10, y + bar * 0.7,
                               CLASS_LABEL[lang][r["tie_class"]], "end",
                               font=12.0))
        # Two segments summing to the class total, with the 2px surface gap the
        # house style puts between adjacent fills.
        body.append(f'<rect x="{left:.1f}" y="{y:.1f}" width="{max(wsame, 0.0):.1f}" '
                    f'height="{bar:.0f}" rx="0" fill="{p["series"][1]}"/>')
        x2 = left + wsame + (2 if wsame > 2 else 0)
        body.append(f'<rect x="{x2:.1f}" y="{y:.1f}" '
                    f'width="{max(wtot - wsame - 2, 0.0):.1f}" height="{bar:.0f}" '
                    f'rx="4" fill="{p["series"][0]}"/>')
        body.append(_axis_text(mode, left + wtot + 9, y + bar * 0.7,
                               f"{n:,}  ({100 * n / max(sum(int(x['n_edges']) for x in rows), 1):.1f}%)",
                               "start", font=11.5))
    height = top + len(rows) * (bar + gapy) + 8

    same_all = sum(int(r["n_same_anchor"]) for r in rows)
    tot = sum(int(r["n_edges"]) for r in rows)
    km = f"{round(float(b['median_tie_km'])):,}" if b.get("median_tie_km") else "—"
    title = {"fr": "La géographie d'un lien",
             "en": "The geography of a tie"}[lang]
    caption = {
        "fr": (f"Les {tot:,} liens traçables classés par les deux extrémités. "
               f"{same_all:,} d'entre eux ({100 * same_all / tot:.1f} %) ne quittent "
               f"pas un seul lieu ; le segment intérieur les montre. Le lien médian "
               f"qui en sort couvre {km} km. Le rang "
               f"colonie–colonie vient en tête, mais "
               f"{int(rows[0]['n_same_territory']):,} de ses liens restent dans un même "
               f"territoire et une partie des entreprises concernées est placée par "
               f"classement, faute d'adresse : lire ce rang comme un maximum."),
        "en": (f"The {tot:,} drawable ties, classified by their two endpoints. "
               f"{same_all:,} of them ({100 * same_all / tot:.1f}%) never leave a "
               f"single place, which is the inner segment; the median tie that does "
               f"leave spans {km} km. Colony–colony leads, but "
               f"{int(rows[0]['n_same_territory']):,} of those ties stay inside one "
               f"territory and some of the firms involved are placed by filing country "
               f"for want of an address, so read that rank as a ceiling."),
    }[lang]
    legend = [(p["series"][1], {"fr": "dans un seul lieu",
                               "en": "within one place"}[lang]),
              (p["series"][0], {"fr": "entre deux lieux",
                                "en": "between two places"}[lang])]
    head = {"fr": ["Classe", "Liens", "Interconnexions", "Dans un lieu",
                   "Dans un territoire"],
            "en": ["Class", "Ties", "Interlocks", "Within one place",
                   "Within one territory"]}[lang]
    table = (head, [[CLASS_LABEL[lang].get(r["tie_class"], r["tie_class"]),
                     f"{int(r['n_edges']):,}", f"{int(r['n_interlocks']):,}",
                     f"{int(r['n_same_anchor']):,}",
                     f"{int(r['n_same_territory']):,}"] for r in rows])
    return "".join(body), height, title, legend, caption, table


def _paris_ranking(d, min_firms=50):
    """Sectors ranked by the share of their placed firms that sit in Paris.

    Computed rather than written down. An earlier draft of fig56's caption
    called finance the most Paris-concentrated sector; it is second, behind
    the transcolonial-groups residual, and first only among the sectors with
    more than a hundred placed firms.
    """
    labels = {r["sector_group"]: r.get("sector_group_en") or r["sector_group"]
              for r in load("sector_centrality.csv")}
    tot: Counter = Counter()
    par: Counter = Counter()
    for cid in d["pos"]:
        g = d["by_id"][cid]["sector_group"]
        if g in ("", "not_a_sector"):
            continue
        tot[g] += 1
        if d["by_id"][cid]["anchor"] == "Paris":
            par[g] += 1
    return sorted(((100 * par[g] / n, labels.get(g, g), g, n)
                   for g, n in tot.items() if n >= min_firms), reverse=True)


# --- fig56: where the banks were -----------------------------------------
def fig_finance_map(d, mode, lang):
    p = PALETTE[mode]
    h = d["height"]
    fin = {cid for cid in d["pos"] if d["by_id"][cid]["sector_group"] == "finance"}
    edges = [(a, b, w) for a, b, w in d["edges"] if a in fin or b in fin]

    def colour_of(cid):
        return p["series"][0] if cid in fin else p["other"]

    body = [graticule(d["box"], mode, h),
            _edge_paths(edges, d["pos"], mode, base_op=0.07),
            _discs(d, mode),
            _nodes(d["pos"], d, mode, colour_of,
                   radius_of=lambda cid: 1.9 if cid in fin else NODE_R),
            _anchor_labels(d, mode, 22)]

    at_paris = sum(1 for cid in fin if d["by_id"][cid]["anchor"] == "Paris")
    anchors = Counter(d["by_id"][cid]["anchor"] for cid in fin)
    top = ", ".join(f"{a} ({n})" for a, n in anchors.most_common(4))
    share = 100 * len(edges) / max(len(d["edges"]), 1)
    fin_paris = 100 * at_paris / max(len(fin), 1)
    rank = _paris_ranking(d)
    place = next((i + 1 for i, r in enumerate(rank) if r[2] == "finance"), 0)
    lead = rank[0] if rank else (0.0, "—", "", 0)
    big = [r for r in rank if r[3] >= 100]
    first_big = big[0][2] == "finance" if big else False
    title = {"fr": "Où étaient les banques",
             "en": "Where the banks were"}[lang]
    caption = {
        "fr": (f"Les {len(fin):,} entreprises de banque et finance que la source situe, "
               f"et les {len(edges):,} liens traçables qui en touchent au moins une — "
               f"{share:.1f} % de tous les liens traçables, pour "
               f"{100 * len(fin) / max(len(d['pos']), 1):.1f} % des entreprises placées. "
               f"{at_paris:,} d'entre elles, soit {fin_paris:.0f} %, sont à Paris ; "
               f"principaux lieux : {top}. C'est le {place}e rang des "
               f"{len(rank)} secteurs d'au moins 50 entreprises placées — "
               f"{lead[1]} mène à {lead[0]:.0f} % sur {lead[3]} entreprises — et le "
               f"{'premier' if first_big else 'rang indiqué'} parmi ceux qui en "
               f"comptent plus de cent. La concentration parisienne appartient au "
               f"noyau, pas à la banque seule : ce que la banque a en propre est sa "
               f"position dans le graphe (§5m), pas sa géographie."),
        "en": (f"The {len(fin):,} banking and finance firms the source can place, and the "
               f"{len(edges):,} drawable ties that touch at least one of them — "
               f"{share:.1f}% of all drawable ties from "
               f"{100 * len(fin) / max(len(d['pos']), 1):.1f}% of the placed firms. "
               f"{at_paris:,} of them ({fin_paris:.0f}%) sit in Paris; largest places: "
               f"{top}. That ranks {place} of the {len(rank)} sectors with 50 or more "
               f"placed firms — {lead[1]} leads at {lead[0]:.0f}% on {lead[3]} firms — "
               f"and {'first' if first_big else 'as shown'} among those with more than a "
               f"hundred. The Paris concentration belongs to the core rather than to "
               f"banking in particular: what is distinctive about finance is its "
               f"position in the graph (§5m), not its geography."),
    }[lang]
    legend = [(p["series"][0], {"fr": "banque et finance",
                               "en": "banking and finance"}[lang]),
              (p["other"], {"fr": "autre secteur", "en": "other sector"}[lang])]
    return "".join(body), h, title, legend, caption, None


FIGURES = [
    ("fig53_full_network_map", fig_full_map),
    ("fig54_paris_or_not", fig_paris),
    ("fig55_tie_geography", fig_tie_geography),
    ("fig56_finance_on_the_map", fig_finance_map),
]


def render_page(d, lang):
    b = d["base"]
    title = {"fr": "Tout le réseau sur la carte du monde",
             "en": "The whole network on the world map"}[lang]
    lede = {
        "fr": (f"La figure 7 place les villes ; celles-ci placent les entreprises. "
               f"{int(b['n_placed_city']) + int(b['n_placed_territory']):,} des "
               f"{int(b['n_graph_firms']):,} entreprises du graphe ont un point, et "
               f"{100 * (int(b['paris_cross_edges']) + int(b['paris_within_edges'])) / max(int(b['n_drawable_edges']), 1):.0f} % "
               f"des liens traçables touchent Paris."),
        "en": (f"Figure 7 places cities; these place firms. "
               f"{int(b['n_placed_city']) + int(b['n_placed_territory']):,} of the "
               f"{int(b['n_graph_firms']):,} firms in the graph get a point, and "
               f"{100 * (int(b['paris_cross_edges']) + int(b['paris_within_edges'])) / max(int(b['n_drawable_edges']), 1):.0f}% "
               f"of the drawable ties touch Paris."),
    }[lang]
    toggle = {"fr": "Basculer le thème", "en": "Toggle theme"}[lang]
    out = [f'<!doctype html><html lang="{lang}"><meta charset="utf-8">',
           f"<title>{esc(title)}</title>",
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           f"<style>{PAGE_CSS}</style>",
           f'<h1>{esc(title)}</h1><p class="lede">{esc(lede)}</p>',
           f'<button onclick="document.documentElement.dataset.theme='
           f'document.documentElement.dataset.theme===\'dark\'?\'light\':\'dark\'">'
           f'{esc(toggle)}</button>']
    for name, fn in FIGURES:
        body, height, ftitle, legend, caption, table = fn(d, "vars", lang)
        if not body:
            continue
        svg = svg_document(body, W, height, "vars", ftitle, legend=legend,
                           caption="")
        out.append(
            f'<figure id="{name}"><h2 style="font-size:16px;margin:0 0 2px">'
            f'{esc(ftitle)}</h2><figcaption>{esc(caption)}</figcaption>{svg}'
            f'{_table_html(table, lang)}</figure>')
    out.append("</html>")
    return "".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=LANGS, default="fr")
    args = ap.parse_args()
    out_dir = FIG_DIR if args.lang == "fr" else os.path.join(FIG_DIR, args.lang)
    ensure_dir(out_dir)

    d = gather()
    written = 0
    for name, fn in FIGURES:
        body, height, title, legend, caption, _ = fn(d, "light", args.lang)
        if not body:
            print(f"  skipped {name}: no data", file=sys.stderr)
            continue
        svg = svg_document(body, W, height, "light", title, legend=legend,
                           caption=caption)
        with open(os.path.join(out_dir, f"{name}.svg"), "w", encoding="utf-8") as fh:
            fh.write(svg)
        written += 1
    with open(os.path.join(out_dir, "world_map.html"), "w", encoding="utf-8") as fh:
        fh.write(render_page(d, args.lang))
    print(f"wrote {written} world-map figures + world_map.html to "
          f"{os.path.relpath(out_dir, os.path.dirname(FIG_DIR))}", file=sys.stderr)


if __name__ == "__main__":
    main()
