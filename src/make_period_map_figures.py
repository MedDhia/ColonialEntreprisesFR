"""Stage 22 - the map, split by period: a series of five, and two summaries.

    python3 src/make_period_map_figures.py
    python3 src/make_period_map_figures.py --lang en

    figures/by_period/map_<period>.svg   one full-width map per period
    figures/fig57_map_by_period.svg      the five as small multiples
    figures/fig58_paris_by_period.svg    Paris's share, and the coverage caveat
    figures/period_maps.html
    data/processed/map_period_summary.csv

Figure 53 draws every drawable tie at once, which flattens forty years into one
picture. These split it on `build_network.PERIODS` — the same five periods
figure 2 uses, so the two are comparable — and **every panel is drawn on the
coordinates `make_world_map_figures.gather()` computed once**. A firm is at the
same pixel in all five, so a difference between panels is a difference in the
data and never a difference in layout.

A firm appears in a period when it has an interlock *dated* to that period.
`edges_company_interlock_by_period.csv` carries 51,818 of the graph's 79,575
edges; the rest are undated and appear in no panel. Add the placement ladder on
top and 24,570 distinct pairs are drawable somewhere in the series.

**The finding, and the thing that could be an artefact of it.** Paris's share
of the drawable ties falls in every period: 63.5%, 51.5%, 40.7%, 36.9%, 26.2%.
That trend is not an artefact of the territory rung, because it survives being
recomputed on the firms with a real street address alone - 82.6%, 65.9%, 62.4%,
60.2%, 42.1%.

But the 1945-1962 panel is thin for a reason that has nothing to do with the
empire. Only **36.2%** of the firms active in it can be placed at all, against
81-86% in every other period, because **1,483 of its 1,484 unplaceable firms are
filed under the transversal *Empire* rubric with no country at all**. That is a
change in how Mennevée catalogued after the war, and it is why fig58 draws the
coverage beside the trend rather than in a footnote: the fourth panel is a
thinner sample, not a thinner network.

These are maps of a **record**, not of an empire. A firm leaves a panel when
the compiler stopped writing about it, which is not the same event as the firm
closing.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import basemap as BM  # noqa: E402
import draw  # noqa: E402
from build_network import PERIODS, read_csv, write_csv  # noqa: E402
from common import ensure_dir  # noqa: E402
from labels import LANGS  # noqa: E402
from make_descriptive_figures import PAGE_CSS, PERIOD_LABEL, _axis_text, _table_html  # noqa: E402
from make_figures import FIG_DIR, PALETTE, esc, svg_document  # noqa: E402
import make_world_map_figures as WM  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
SUMMARY = os.path.join(PROC, "map_period_summary.csv")

W = WM.W
ORDER = [name for name, _lo, _hi in PERIODS]
PERIOD_FR = {
    "pre_1914": "avant 1914", "1914_1929": "1914–1929",
    "1930_1944": "1930–1944", "1945_1962": "1945–1962",
    "post_1962": "après 1962",
}
SMALL_COLS = 2          # small-multiple grid
SMALL_GAP = 26.0
LABEL_TOP_FULL = 26     # anchors labelled on a full-width panel
LABEL_TOP_SMALL = 8


def plabel(period: str, lang: str) -> str:
    return PERIOD_LABEL[period] if lang == "en" else PERIOD_FR[period]


def gather() -> dict:
    """Stage 21's coordinates, plus the dated edges split by period."""
    d = WM.gather()
    by_period: dict[str, list[tuple[str, str, int]]] = {p: [] for p in ORDER}
    dated = 0
    for r in read_csv(os.path.join(PROC, "edges_company_interlock_by_period.csv")):
        p = r["period"]
        if p not in by_period:
            continue
        dated += 1
        a, b = r["company_id_1"], r["company_id_2"]
        if a in d["pos"] and b in d["pos"]:
            by_period[p].append((a, b, int(r["weight"])))
    d["by_period"] = by_period
    d["n_dated_edges"] = dated
    d["stats"] = [_period_stats(d, p) for p in ORDER]
    return d


def _period_stats(d: dict, period: str) -> dict:
    """One row per period. Everything a caption says is computed here."""
    edges = d["by_period"][period]
    by_id = d["by_id"]
    firms = {x for a, b, _w in edges for x in (a, b)}
    anchors = Counter(by_id[f]["anchor"] for f in firms)
    paris = {f for f in firms if by_id[f]["anchor"] == "Paris"}
    touching = sum(1 for a, b, _w in edges if a in paris or b in paris)

    # The same share on the firms with a street address alone. The territory
    # rung places a firm at a filing category, and filing changed after the
    # war, so the trend has to be shown to survive without it.
    addr = [(a, b) for a, b, _w in edges
            if by_id[a]["placement_level"] == "city"
            and by_id[b]["placement_level"] == "city"]
    addr_paris = sum(1 for a, b in addr
                     if by_id[a]["anchor"] == "Paris" or by_id[b]["anchor"] == "Paris")

    # Coverage: of the firms with a tie in this period, how many can be placed.
    active = _active_firms(d, period)
    lvl = Counter(by_id[f]["placement_level"] for f in active if f in by_id)
    placed = lvl["city"] + lvl["territory"]
    transversal = sum(1 for f in active
                      if by_id.get(f, {}).get("reason") == "no country listed")
    return {
        "period": period,
        "n_dated_edges": len(_raw_edges(d, period)),
        "n_drawable_edges": len(edges),
        "n_interlocks": sum(w for _a, _b, w in edges),
        "n_firms_drawn": len(firms),
        "n_anchors": len(anchors),
        "n_active_firms": len(active),
        "n_placed_firms": placed,
        "share_firms_placed": f"{placed / max(len(active), 1):.4f}",
        "n_no_country_firms": transversal,
        "n_paris_firms": len(paris),
        "n_paris_edges": touching,
        "paris_share": f"{touching / max(len(edges), 1):.4f}",
        "n_address_edges": len(addr),
        "n_address_paris_edges": addr_paris,
        "paris_share_address_only": f"{addr_paris / max(len(addr), 1):.4f}",
        "top_anchors": "; ".join(f"{a} ({n})" for a, n in anchors.most_common(5)),
    }


_raw_cache: dict[str, list] = {}


def _raw_edges(d: dict, period: str) -> list:
    """Dated edges in this period before the placement filter, for coverage."""
    if not _raw_cache:
        for r in read_csv(os.path.join(
                PROC, "edges_company_interlock_by_period.csv")):
            _raw_cache.setdefault(r["period"], []).append(
                (r["company_id_1"], r["company_id_2"]))
    return _raw_cache.get(period, [])


def _active_firms(d: dict, period: str) -> set[str]:
    return {x for a, b in _raw_edges(d, period) for x in (a, b)}


# --- one map ---------------------------------------------------------------
def period_panel(d, period, mode, proj, pos, clip_id, dy=0.0, labels=True,
                 node_r=WM.NODE_R):
    """One period's map: basemap, then that period's edges and nodes."""
    return (BM.basemap_svg(proj, PALETTE[mode], clip_id, dy, labels=labels)
            + _panel_data(d, period, mode,
                          {c: (x, y + dy) for c, (x, y) in pos.items()},
                          r=node_r))


def _legend(mode, lang):
    p = PALETTE[mode]
    return [(p["series"][0], "Paris"),
            (p["series"][2], {"fr": "ailleurs, actif dans la période",
                              "en": "elsewhere, active in the period"}[lang]),
            (p["other"], {"fr": "sans lien daté dans la période",
                          "en": "no dated tie in the period"}[lang])]


def full_map(d, period, mode, lang):
    """A full-width map of one period, for `figures/by_period/`."""
    st = next(s for s in d["stats"] if s["period"] == period)
    body = period_panel(d, period, mode, d["proj"], d["pos"], f"clip_{period}")
    body += WM._anchor_labels(d, mode, LABEL_TOP_FULL)
    title = {"fr": f"Le réseau sur la carte — {plabel(period, lang)}",
             "en": f"The network on the map — {plabel(period, lang)}"}[lang]
    share = 100 * float(st["paris_share"])
    addr = 100 * float(st["paris_share_address_only"])
    cover = 100 * float(st["share_firms_placed"])
    caption = {
        "fr": (f"{st['n_drawable_edges']:,} liens traçables datés de cette période, "
               f"entre {st['n_firms_drawn']:,} entreprises réparties sur "
               f"{st['n_anchors']} lieux ; les entreprises en gris n'ont aucun lien "
               f"daté ici. {share:.1f} % de ces liens touchent Paris — "
               f"{addr:.1f} % si l'on ne garde que les entreprises ayant une "
               f"adresse. Couverture : {cover:.1f} % des "
               f"{st['n_active_firms']:,} entreprises actives dans la période "
               f"peuvent être situées. Mêmes coordonnées que les figures 53 à 56."),
        "en": (f"{st['n_drawable_edges']:,} drawable ties dated to this period, among "
               f"{st['n_firms_drawn']:,} firms across {st['n_anchors']} places; the grey "
               f"firms have no dated tie here. {share:.1f}% of those ties touch Paris — "
               f"{addr:.1f}% if only firms with a street address are counted. Coverage: "
               f"{cover:.1f}% of the {st['n_active_firms']:,} firms active in the period "
               f"can be placed at all. Same coordinates as figures 53 to 56."),
    }[lang]
    return body, d["height"], title, _legend(mode, lang), caption


# --- fig57: the five as small multiples -----------------------------------
def fig_small_multiples(d, mode, lang):
    p = PALETTE[mode]
    cols = SMALL_COLS
    panel_w = (W - SMALL_GAP * (cols - 1)) / cols
    proj = BM.Robinson(panel_w, pad=8.0, lat_min=WM.LAT_MIN, lat_max=WM.LAT_MAX)
    scale = panel_w / W

    # The same coordinates, scaled: a panel is figure 53 shrunk, not relaid out.
    def place(col, row):
        ox = col * (panel_w + SMALL_GAP)
        oy = row * (proj.height + 34.0)
        return ox, oy

    rows = math.ceil(len(ORDER) / cols)
    body = []
    for i, period in enumerate(ORDER):
        col, row = i % cols, i // cols
        ox, oy = place(col, row)
        top = oy + 24.0
        # Stage 21's pixels, rescaled. A Robinson fitted to the panel width is
        # the full-width one scaled linearly, so the basemap and the rescaled
        # firm positions agree by construction rather than by adjustment.
        pos = {c: (ox + x * scale, top + y * scale)
               for c, (x, y) in d["pos"].items()}
        body.append(f'<g transform="translate({ox:.1f} {top:.1f})">'
                    f'{BM.basemap_svg(proj, p, f"clip57_{period}", labels=False)}'
                    f'</g>')
        body.append(_panel_data(d, period, mode, pos, r=WM.NODE_R * 0.75))
        st = next(s for s in d["stats"] if s["period"] == period)
        body.append(draw.halo_text(
            mode, ox + 2, oy + 16, plabel(period, lang), "start", font=13.0,
            weight="600"))
        body.append(_axis_text(
            mode, ox + panel_w - 2, oy + 16,
            f"{st['n_drawable_edges']:,} · Paris {100 * float(st['paris_share']):.0f}%",
            "end", font=11.0))
    # The grid leaves one cell empty. The caveat that most needs to travel
    # with these maps goes in it, rather than only in a caption a cropped
    # screenshot would lose.
    if len(ORDER) < rows * cols:
        ox, oy = place(len(ORDER) % cols, len(ORDER) // cols)
        body.append(_coverage_note(d, mode, lang, ox, oy + 24.0, panel_w))
    height = rows * (proj.height + 34.0) + 24.0

    first, last = d["stats"][0], d["stats"][-1]
    title = {"fr": "Le réseau sur la carte, période par période",
             "en": "The network on the map, period by period"}[lang]
    caption = {
        "fr": (f"Cinq panneaux, une seule mise en page : une entreprise occupe le même "
               f"pixel dans les cinq, donc une différence entre panneaux est une "
               f"différence dans les données. La part parisienne des liens traçables "
               f"tombe de {100 * float(first['paris_share']):.1f} % à "
               f"{100 * float(last['paris_share']):.1f} %. Attention au panneau "
               f"1945–1962 : seules {100 * float(d['stats'][3]['share_firms_placed']):.1f} % "
               f"de ses entreprises peuvent être situées, contre {_other_cover(d)} ailleurs, "
               f"parce que {d['stats'][3]['n_no_country_firms']:,} d'entre elles sont "
               f"classées sous la rubrique transversale *Empire* sans aucun pays. "
               f"Voir la figure 58."),
        "en": (f"Five panels, one layout: a firm holds the same pixel in all five, so a "
               f"difference between panels is a difference in the data. Paris's share of "
               f"the drawable ties falls from {100 * float(first['paris_share']):.1f}% to "
               f"{100 * float(last['paris_share']):.1f}%. Read the 1945–1962 panel with "
               f"care: only {100 * float(d['stats'][3]['share_firms_placed']):.1f}% of its "
               f"firms can be placed, against {_other_cover(d)} in every other period, because "
               f"{d['stats'][3]['n_no_country_firms']:,} of them are filed under the "
               f"transversal *Empire* rubric with no country at all. See figure 58."),
    }[lang]
    table = _summary_table(d, lang)
    return "".join(body), height, title, _legend(mode, lang), caption, table


def _other_cover(d, worst="1945_1962") -> str:
    """The coverage band of every period but the thin one, as `81–86%`.

    Written out rather than hardcoded: this range has moved with every rebuild
    of the graph, and a caption should not carry a number a rerun falsifies.
    """
    vs = [float(s["share_firms_placed"]) for s in d["stats"]
          if s["period"] != worst]
    return f"{min(vs) * 100:.0f}–{max(vs) * 100:.0f}%"


def _coverage_note(d, mode, lang, ox, oy, width):
    """The per-period coverage, printed in the grid's spare cell."""
    p = PALETTE[mode]
    head = {"fr": "Part des entreprises de la période que l'on peut situer",
            "en": "Share of each period's firms that can be placed"}[lang]
    out = [_axis_text(mode, ox + 6, oy + 26, head, "start", font=12.5)]
    y = oy + 52
    for st in d["stats"]:
        v = float(st["share_firms_placed"])
        bad = v < 0.5
        colour = p["series"][1] if bad else p["text_secondary"]
        out.append(_axis_text(mode, ox + 6, y, plabel(st["period"], lang),
                              "start", font=11.5))
        # A bar, so the odd one out is visible before the number is read.
        bar_x, bar_w = ox + 132, min(240.0, width - 220)
        out.append(f'<rect x="{bar_x:.1f}" y="{y - 9:.1f}" '
                   f'width="{bar_w * v:.1f}" height="11" rx="3" '
                   f'fill="{p["series"][1] if bad else p["other"]}"/>')
        out.append(f'<text x="{bar_x + bar_w + 8:.1f}" y="{y:.1f}" '
                   f'font-size="11.5" font-family="ui-sans-serif,system-ui,'
                   f'sans-serif" fill="{colour}">{v * 100:.1f}%</text>')
        y += 24
    tail = {
        "fr": (f"1945–1962 est l'exception : {d['stats'][3]['n_no_country_firms']:,} "
               f"de ses entreprises sont classées sous la rubrique transversale "
               f"Empire, sans aucun pays. Ce panneau est un échantillon plus "
               f"mince, pas un réseau plus mince."),
        "en": (f"1945–1962 is the outlier: {d['stats'][3]['n_no_country_firms']:,} "
               f"of its firms are filed under the transversal Empire rubric "
               f"with no country at all. That panel is a thinner sample, not a "
               f"thinner network."),
    }[lang]
    for i, line in enumerate(_wrap(tail, 58)):
        out.append(_axis_text(mode, ox + 6, y + 14 + i * 15, line, "start",
                              font=11.5))
    return "".join(out)


def _wrap(text, width):
    lines, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines


def _panel_data(d, period, mode, pos, r=WM.NODE_R):
    """The edges and nodes of one period, on coordinates already placed.

    Dormant firms first and smaller, live ones on top: a panel is about who is
    in the network this period, and a grey dot behind a coloured one is the
    honest way to show a firm the record has paused on rather than dropped.
    """
    p = PALETTE[mode]
    edges = d["by_period"][period]
    live = {x for a, b, _w in edges for x in (a, b)}
    paris = {f for f in live if d["by_id"][f]["anchor"] == "Paris"}

    def colour_of(cid):
        if cid not in live:
            return p["other"]
        return p["series"][0] if cid in paris else p["series"][2]

    return (WM._edge_paths(edges, pos, mode, 0.0, base_op=0.08)
            + WM._nodes([c for c in pos if c not in live], d, mode, colour_of,
                        0.0, r=r * 0.62, pos=pos)
            + WM._nodes(sorted(live), d, mode, colour_of, 0.0, r=r, pos=pos))


def _summary_table(d, lang):
    head = {"fr": ["Période", "Liens traçables", "Entreprises", "Lieux",
                   "Part Paris", "Part Paris (adresses)", "Couverture"],
            "en": ["Period", "Drawable ties", "Firms", "Places", "Paris share",
                   "Paris share (addresses only)", "Coverage"]}[lang]
    rows = []
    for st in d["stats"]:
        rows.append([
            plabel(st["period"], lang), f"{st['n_drawable_edges']:,}",
            f"{st['n_firms_drawn']:,}", f"{st['n_anchors']}",
            f"{100 * float(st['paris_share']):.1f}%",
            f"{100 * float(st['paris_share_address_only']):.1f}%",
            f"{100 * float(st['share_firms_placed']):.1f}%",
        ])
    return head, rows


# --- fig58: the trend, and the coverage that could explain it away ---------
def fig_paris_trend(d, mode, lang):
    """Two panels, never one chart with two axes.

    The left panel is Paris's share of the drawable ties; the right is what
    fraction of each period's firms can be placed at all. They are different
    quantities about different denominators, and putting them on one pair of
    axes — which is what a second y-axis is — would invite exactly the reading
    the figure exists to prevent.
    """
    p = PALETTE[mode]
    st = d["stats"]
    gap = 76.0
    pw = (W - gap) / 2
    left, right = 54.0, 16.0
    top, plot_h = 46.0, 250.0
    n = len(st)

    def x_of(panel, i):
        """Band centres, not endpoints.

        Putting the first and last points on the plot's edges pushed half of
        the last bar off the canvas and ran the first one into the axis
        labels. Band centres also line the two panels up on the same period.
        """
        x0 = panel * (pw + gap) + left
        span = pw - left - right
        return x0 + span * ((i + 0.5) / n)

    def y_of(v):
        return top + plot_h * (1 - v)

    body = []
    # Gridlines and the axis, shared by both panels.
    for panel in (0, 1):
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = y_of(frac)
            x0, x1 = panel * (pw + gap) + left, panel * (pw + gap) + pw - right
            body.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" '
                        f'y2="{y:.1f}" stroke="{p["hairline"]}" stroke-width="0.8"/>')
            body.append(_axis_text(mode, x0 - 8, y + 3.6, f"{frac * 100:.0f}%",
                                   "end", font=10.5))
        for i, s in enumerate(st):
            body.append(_axis_text(mode, x_of(panel, i), top + plot_h + 18,
                                   plabel(s["period"], lang), "middle", font=10.5))

    # Left: two lines, both shares of ties, so one axis is honest.
    series = [
        (0, "paris_share", p["series"][0],
         {"fr": "toutes entreprises situées", "en": "all placed firms"}[lang]),
        (0, "paris_share_address_only", p["series"][2],
         {"fr": "adresse seule", "en": "street address only"}[lang]),
    ]
    for panel, key, colour, _lab in series:
        pts = [(x_of(panel, i), y_of(float(s[key]))) for i, s in enumerate(st)]
        body.append('<path d="M' + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
                    + f'" fill="none" stroke="{colour}" stroke-width="2" '
                    f'stroke-linejoin="round"/>')
        for (x, y), s in zip(pts, st):
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.2" '
                        f'fill="{colour}" stroke="{p["surface"]}" '
                        f'stroke-width="2"/>')
        body.append(draw.halo_text(
            mode, pts[0][0], pts[0][1] - 12, f"{100 * float(st[0][key]):.0f}%",
            "middle", font=10.5))
        body.append(draw.halo_text(
            mode, pts[-1][0], pts[-1][1] - 12, f"{100 * float(st[-1][key]):.0f}%",
            "middle", font=10.5))

    # Right: coverage as bars, because it is a property of each period on its
    # own and joining the points would assert a trend that is not there.
    span = pw - left - right
    bw = min(58.0, span / (n + 1))
    for i, s in enumerate(st):
        v = float(s["share_firms_placed"])
        x = x_of(1, i) - bw / 2
        y = y_of(v)
        colour = p["series"][1] if v < 0.5 else p["other"]
        body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                    f'height="{top + plot_h - y:.1f}" rx="4" fill="{colour}"/>')
        body.append(_axis_text(mode, x + bw / 2, y - 6, f"{v * 100:.0f}%",
                               "middle", font=10.5))

    heads = [{"fr": "Part des liens traçables qui touchent Paris",
              "en": "Share of drawable ties that touch Paris"}[lang],
             {"fr": "Part des entreprises de la période que l'on peut situer",
              "en": "Share of the period's firms that can be placed"}[lang]]
    for panel, h in enumerate(heads):
        body.append(_axis_text(mode, panel * (pw + gap) + left, 24, h, "start",
                               font=12.5))
    height = top + plot_h + 40

    title = {"fr": "Paris recule — et ce que la couverture peut en expliquer",
             "en": "Paris recedes — and what coverage could explain away"}[lang]
    bad = d["stats"][3]
    caption = {
        "fr": (f"À gauche, la part parisienne tombe à chaque période, de "
               f"{100 * float(st[0]['paris_share']):.1f} % à "
               f"{100 * float(st[-1]['paris_share']):.1f} %. Le second tracé refait le "
               f"calcul sur les seules entreprises ayant une adresse de rue — là où la "
               f"position est un fait sur l'entreprise et non sur le classement du "
               f"catalogue — et la tendance tient : "
               f"{100 * float(st[0]['paris_share_address_only']):.1f} % à "
               f"{100 * float(st[-1]['paris_share_address_only']):.1f} %. À droite, la "
               f"raison de se méfier tout de même : la couverture s'effondre en "
               f"1945–1962, où {bad['n_no_country_firms']:,} des entreprises actives "
               f"sont classées sous la rubrique transversale *Empire* sans aucun pays. "
               f"Ce panneau est un échantillon plus mince, pas un réseau plus mince."),
        "en": (f"Left: Paris's share falls in every period, from "
               f"{100 * float(st[0]['paris_share']):.1f}% to "
               f"{100 * float(st[-1]['paris_share']):.1f}%. The second line recomputes it "
               f"on firms with a street address alone — where position is a fact about "
               f"the firm rather than about the catalogue's filing — and the trend "
               f"survives: {100 * float(st[0]['paris_share_address_only']):.1f}% to "
               f"{100 * float(st[-1]['paris_share_address_only']):.1f}%. Right: the reason "
               f"to be careful anyway. Coverage collapses in 1945–1962, where "
               f"{bad['n_no_country_firms']:,} of the active firms are filed under the "
               f"transversal *Empire* rubric with no country at all. That panel is a "
               f"thinner sample, not a thinner network."),
    }[lang]
    legend = [(p["series"][0], {"fr": "toutes entreprises situées",
                               "en": "all placed firms"}[lang]),
              (p["series"][2], {"fr": "adresse seule",
                                "en": "street address only"}[lang]),
              (p["series"][1], {"fr": "couverture sous 50 %",
                                "en": "coverage below 50%"}[lang])]
    return "".join(body), height, title, legend, caption, _summary_table(d, lang)


FIGURES = [
    ("fig57_map_by_period", fig_small_multiples),
    ("fig58_paris_by_period", fig_paris_trend),
]


def render_page(d, lang):
    st = d["stats"]
    title = {"fr": "La carte, période par période",
             "en": "The map, period by period"}[lang]
    lede = {
        "fr": (f"Figure 53 aplatit quarante ans en une image. Ces cartes la découpent "
               f"sur les cinq périodes de la figure 2, sur une seule mise en page. "
               f"La part parisienne des liens traçables passe de "
               f"{100 * float(st[0]['paris_share']):.1f} % à "
               f"{100 * float(st[-1]['paris_share']):.1f} % — mais ce sont des cartes "
               f"d'un fonds documentaire, pas d'un empire."),
        "en": (f"Figure 53 flattens forty years into one picture. These split it on the "
               f"five periods of figure 2, on one layout. Paris's share of the drawable "
               f"ties falls from {100 * float(st[0]['paris_share']):.1f}% to "
               f"{100 * float(st[-1]['paris_share']):.1f}% — but these are maps of a "
               f"record, not of an empire."),
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
        svg = svg_document(body, W, height, "vars", ftitle, legend=legend,
                           caption="")
        out.append(f'<figure id="{name}"><h2 style="font-size:16px;margin:0 0 2px">'
                   f'{esc(ftitle)}</h2><figcaption>{esc(caption)}</figcaption>'
                   f'{svg}{_table_html(table, lang)}</figure>')
    for period in ORDER:
        body, height, ftitle, legend, caption = full_map(d, period, "vars", lang)
        svg = svg_document(body, W, height, "vars", ftitle, legend=legend,
                           caption="")
        out.append(f'<figure id="map_{period}">'
                   f'<h2 style="font-size:16px;margin:0 0 2px">{esc(ftitle)}</h2>'
                   f'<figcaption>{esc(caption)}</figcaption>{svg}</figure>')
    out.append("</html>")
    return "".join(out)


def write_summary(d) -> None:
    cols = list(d["stats"][0])
    write_csv(SUMMARY, d["stats"], cols)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=LANGS, default="fr")
    args = ap.parse_args()
    out_dir = FIG_DIR if args.lang == "fr" else os.path.join(FIG_DIR, args.lang)
    per_dir = os.path.join(out_dir, "by_period")
    ensure_dir(per_dir)

    d = gather()
    if args.lang == "fr":
        write_summary(d)

    for name, fn in FIGURES:
        body, height, title, legend, caption, _ = fn(d, "light", args.lang)
        with open(os.path.join(out_dir, f"{name}.svg"), "w", encoding="utf-8") as fh:
            fh.write(svg_document(body, W, height, "light", title,
                                  legend=legend, caption=caption))
    for period in ORDER:
        body, height, title, legend, caption = full_map(d, period, "light",
                                                        args.lang)
        with open(os.path.join(per_dir, f"map_{period}.svg"), "w",
                  encoding="utf-8") as fh:
            fh.write(svg_document(body, W, height, "light", title,
                                  legend=legend, caption=caption))
    with open(os.path.join(out_dir, "period_maps.html"), "w",
              encoding="utf-8") as fh:
        fh.write(render_page(d, args.lang))
    print(f"wrote {len(FIGURES)} figures + {len(ORDER)} period maps + "
          f"period_maps.html to {os.path.relpath(out_dir, os.path.dirname(FIG_DIR))}",
          file=sys.stderr)
    for s in d["stats"]:
        print(f"  {s['period']:11} {s['n_drawable_edges']:6,} ties  "
              f"Paris {100 * float(s['paris_share']):5.1f}%  "
              f"(addresses {100 * float(s['paris_share_address_only']):5.1f}%)  "
              f"coverage {100 * float(s['share_firms_placed']):5.1f}%",
              file=sys.stderr)


if __name__ == "__main__":
    main()
