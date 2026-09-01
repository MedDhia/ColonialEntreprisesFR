"""Stage 11 - the descriptive figures.

    python3 src/make_descriptive_figures.py            # -> figures/fig8..fig17
    python3 src/make_descriptive_figures.py --lang en  # -> figures/en/

Every figure this repository had before this stage was a network: node-link
diagrams, a territory matrix, a map. Topology is what the dataset is *for*, but
it is not what a reader needs first. Before anyone computes a centrality they
have to know when the observations were made, how thin the coverage is outside
four territories, how much of the network rests on a single shared director,
and that one year holds a sixth of all the ties. None of that was visible
anywhere, and a caveat that lives only in prose is a caveat most readers skip.

Ten figures, each answering one question the network diagrams cannot:

    fig8   ties by year, split by source genre       when were the ties observed
    fig9   genre composition within each period      can periods be compared
    fig10  seats per person                          how concentrated is the elite
    fig11  board size per firm-year                  what a "board" is here
    fig12  ties by territory                         where the data actually is
    fig13  ties by sector                            what the empire was made of
    fig14  role composition                          what a "tie" actually records
    fig15  indigenous share by territory             the headline finding
    fig16  brokers against hubs                      structural position, two ways
    fig17  shared directors per interlock            how fragile the edges are

Design follows the same rules as `make_figures.py`, and the palette is that
module's, extended from three categorical slots to five for the genre figures.
Five slots validate on the *adjacent* pairlist, which is what a stacked bar
uses; the scatter is an all-pairs form and is capped at three, as the palette
documentation requires. Aqua, yellow and magenta sit below 3:1 on the light
surface, so the relief rule applies throughout: every figure carries direct
value labels, and the HTML page ships a table view of each.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_network import PERIODS, read_csv  # noqa: E402
from common import ensure_dir  # noqa: E402
from labels import LANGS, localise  # noqa: E402
from make_figures import (  # noqa: E402
    FIG_DIR, PALETTE, _text_width, esc, svg_document, trim_to_width,
)

# Categorical slots 4 and 5, taken from the reference palette in the documented
# order rather than invented. Slots 1-3 are already in make_figures.PALETTE.
EXTRA_SERIES = {
    "light": ["#eda100", "#e87ba4"],
    "dark": ["#c98500", "#d55181"],
    # The "vars" mode emits CSS custom properties so one SVG serves both themes
    # inside the page; the page defines --s4 and --s5 from the same two steps.
    "vars": ["var(--s4)", "var(--s5)"],
}


def series(mode: str, n: int) -> list[str]:
    """The first `n` categorical hues, in the fixed documented order."""
    pool = list(PALETTE[mode]["series"]) + EXTRA_SERIES[mode]
    if n > len(pool):
        raise ValueError(f"{n} series requested; the palette defines {len(pool)}")
    return pool[:n]


GENRES = ["dossier", "person_index", "prose", "annotation", "biographical"]
GENRE_LABEL = {
    "fr": {"dossier": "dossier", "person_index": "index de personnes",
           "prose": "prose", "annotation": "annotation",
           "biographical": "biographique"},
    "en": {"dossier": "dossier", "person_index": "person index",
           "prose": "prose", "annotation": "annotation",
           "biographical": "biographical"},
}
PERIOD_LABEL = {
    "pre_1914": "pre-1914", "1914_1929": "1914–1929", "1930_1944": "1930–1944",
    "1945_1962": "1945–1962", "post_1962": "post-1962",
}

AXIS_FONT = 11.0
VALUE_FONT = 10.5
TITLE_FONT = 13.5
BAR_GAP = 2.0            # the palette's 2px surface gap between adjacent fills


def _fmt(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", " ")


def _axis_text(mode: str, x: float, y: float, text: str, anchor: str = "start",
               font: float = AXIS_FONT, muted: bool = False) -> str:
    """Axis and value ink always uses a text token, never a series colour."""
    p = PALETTE[mode]
    fill = p["text_muted"] if muted else p["text_secondary"]
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-size="{font}" fill="{fill}">{esc(text)}</text>')


def _grid_line(mode: str, x1, y1, x2, y2) -> str:
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{PALETTE[mode]["hairline"]}" stroke-width="1"/>')



_TABLE_HEAD = {
    "fr": {"year": "année", "n": "observations", "period": "période",
           "share": "part", "seats": "sièges", "people": "personnes",
           "size": "taille", "fy": "firmes-années", "terr": "territoire",
           "sect": "secteur", "ties": "ties", "role": "rôle", "pct": "%",
           "firm": "firme", "gap": "rangs gagnés",
           "w": "administrateurs partagés", "edges": "liens"},
    "en": {"year": "year", "n": "observations", "period": "period",
           "share": "share", "seats": "seats", "people": "people",
           "size": "size", "fy": "firm-years", "terr": "territory",
           "sect": "sector", "ties": "ties", "role": "role", "pct": "%",
           "firm": "firm", "gap": "ranks gained",
           "w": "shared directors", "edges": "edges"},
}


def H(lang: str, key: str) -> str:
    """A table-header word. The tables are the relief the palette requires, so
    they are localised like everything else a reader actually reads."""
    return _TABLE_HEAD[lang][key]


# --- chart primitives -----------------------------------------------------
def hbars(rows, width, mode, label_w=210.0, row_h=25.0, value_fmt=_fmt,
          colour=None, top_note=""):
    """Horizontal bars: the form for a ranked magnitude with long labels.

    Rows are `(label, value, tooltip)`. A single series carries no legend - the
    title names it - and every bar is directly labelled, which is also the
    relief the light-mode contrast warning requires.
    """
    p = PALETTE[mode]
    fill = colour or p["series"][0]
    hi = max((v for _, v, _ in rows), default=1) or 1
    plot_w = width - label_w - 74.0
    parts, y = [], 0.0
    if top_note:
        parts.append(_axis_text(mode, label_w, 12.0, top_note, font=AXIS_FONT, muted=True))
        y = 22.0
    for label, value, tip in rows:
        bar = plot_w * (value / hi)
        cy = y + row_h / 2
        parts.append(
            f'<g class="mk"><title>{esc(tip)}</title>'
            f'{_axis_text(mode, label_w - 10, cy + 3.8, trim_to_width(label, AXIS_FONT, label_w - 14), "end")}'
            # 4px rounded data-end, anchored to the baseline at x=label_w
            f'<rect x="{label_w:.1f}" y="{y + 4:.1f}" width="{max(bar, 2.0):.1f}" '
            f'height="{row_h - 8 - BAR_GAP:.1f}" rx="4" fill="{fill}"/>'
            f'{_axis_text(mode, label_w + max(bar, 2.0) + 7, cy + 3.8, value_fmt(value), "start", VALUE_FONT)}'
            f'</g>'
        )
        y += row_h
    return "".join(parts), y


def columns(rows, width, height, mode, log=False, label_every=1, colour=None,
            x_title="", y_title="", hi=None, max_bar=None, value_fmt=None,
            tick_fmt=None):
    """Vertical columns: the form for a distribution over an ordered axis.

    `log` switches the value axis to log10 for the counts that span four orders
    of magnitude; the axis is labelled as such, because an unlabelled log scale
    reads as a linear one and understates the tail by a factor of thousands.

    `hi` pins the top of the value axis. A share chart has to be scaled to 100%,
    not to its own maximum: scaled to the data, a series running 46-74% fills
    the canvas top to bottom and reads as "from nothing to everything".

    `max_bar` caps the bar width. With five categories the default step leaves
    a 190px bar, which is a block of colour rather than a mark.

    `value_fmt` direct-labels each bar. Three of the light-mode slots sit below
    3:1 on the surface, so where there is room for direct labels the palette's
    relief rule wants them.
    """
    p = PALETTE[mode]
    fill = colour or p["series"][0]
    # Direct labels sit above their bar, so the tallest one needs a row of its
    # own; at the default headroom it landed on top of the axis title.
    left, bottom, top = 58.0, 34.0, (30.0 if value_fmt else 16.0)
    plot_w, plot_h = width - left - 12.0, height - bottom - top
    hi = hi or max((r[1] for r in rows), default=1) or 1
    fmt_tick = tick_fmt or _fmt

    def ypos(v):
        if not log:
            return top + plot_h * (1 - v / hi)
        if v <= 0:
            return top + plot_h
        return top + plot_h * (1 - math.log10(v) / math.log10(hi))

    parts = []
    ticks = ([10 ** k for k in range(int(math.log10(hi)) + 1)] if log
             else [hi * f for f in (0, 0.25, 0.5, 0.75, 1.0)])
    for t in ticks:
        yt = ypos(t)
        parts.append(_grid_line(mode, left, yt, left + plot_w, yt))
        parts.append(_axis_text(mode, left - 8, yt + 3.6, fmt_tick(t), "end", muted=True))
    step = plot_w / max(len(rows), 1)
    bw = max(step - BAR_GAP, 1.2)
    if max_bar:
        bw = min(bw, max_bar)
    inset = (step - bw) / 2 if max_bar else 0.0
    for i, row in enumerate(rows):
        # A row may carry its own fill as a fourth field. That is not a rank
        # colour: it is used where the bars split into two *named* categories
        # (a shell that is a clique and one that is not), which ships a legend.
        label, value, tip = row[:3]
        bar_fill = row[3] if len(row) > 3 else fill
        x = left + i * step + inset
        yv = ypos(value)
        # On a log axis a count of zero is not a short bar, it is no bar. The
        # 1px stub the height floor produced read as "one", which turned the
        # empty k-shells between 46 and 71 into a solid run of occupied ones.
        if not (log and value <= 0):
            parts.append(
                f'<g class="mk"><title>{esc(tip)}</title>'
                f'<rect x="{x:.1f}" y="{yv:.1f}" width="{bw:.1f}" '
                f'height="{max(top + plot_h - yv, 1.0):.1f}" rx="{min(4.0, bw / 2):.1f}" fill="{bar_fill}"/>'
                f'</g>'
            )
            if value_fmt:
                parts.append(_axis_text(mode, x + bw / 2, yv - 5, value_fmt(value),
                                        "middle", VALUE_FONT))
        if label and i % label_every == 0:
            parts.append(_axis_text(mode, x + bw / 2, top + plot_h + 15, label,
                                    "middle", muted=True))
    parts.append(_grid_line(mode, left, top + plot_h, left + plot_w, top + plot_h))
    if y_title:
        # Left-aligned at the canvas edge: right-anchoring it to the axis pushed
        # any title wider than the 58px gutter off the left of the viewBox.
        # Pinned to the top of the canvas rather than to the plot: with direct
        # labels the plot starts 30px down and the title landed on the topmost
        # tick, which is wider than the gutter and so sits under the title.
        parts.append(_axis_text(mode, 0, min(top - 5, 11.0), y_title, "start",
                                muted=True))
    if x_title:
        parts.append(_axis_text(mode, left + plot_w, top + plot_h + 30, x_title,
                                "end", muted=True))
    return "".join(parts)


def stacked(groups, width, height, mode, keys, key_label, share=False,
            label_every=1):
    """Stacked columns, one stack per group, segments in fixed `keys` order.

    Colour follows the key, never its rank within a stack: a genre keeps its
    hue whether it is the largest segment or absent.
    """
    cols = series(mode, len(keys))
    left, bottom, top = 58.0, 34.0, 16.0
    plot_w, plot_h = width - left - 12.0, height - bottom - top
    totals = [sum(g[1].get(k, 0) for k in keys) for g in groups]
    hi = 1.0 if share else (max(totals, default=1) or 1)
    parts: list[str] = []
    for f in (0, .25, .5, .75, 1.0):
        yt = top + plot_h * (1 - f)
        label = f"{f:.0%}" if share else _fmt(hi * f)
        parts.append(_grid_line(mode, left, yt, left + plot_w, yt))
        parts.append(_axis_text(mode, left - 8, yt + 3.6, label, "end", muted=True))
    step = plot_w / max(len(groups), 1)
    # Keep the 2px surface gap, but do not spend three of them on the inset when
    # 150-odd groups leave only a few pixels each: fig8's year columns became
    # 2px slivers and the interwar hump stopped reading as a shape.
    bw = max(step - (BAR_GAP * 3 if step > 24 else BAR_GAP), 2.0)
    for i, (name, counts) in enumerate(groups):
        total = totals[i] or 1
        x = left + i * step + (step - bw) / 2
        acc = 0.0
        for k, colour in zip(keys, cols):
            v = counts.get(k, 0)
            if not v:
                continue
            frac = (v / total) if share else (v / hi)
            h = plot_h * frac
            y = top + plot_h * (1 - (acc + frac))
            acc += frac
            pct = v / total
            parts.append(
                f'<g class="mk"><title>{esc(f"{name} · {key_label(k)}: {_fmt(v)} ({pct:.1%})")}</title>'
                # 2px surface gap between stacked segments
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                f'height="{max(h - BAR_GAP, 0.8):.1f}" rx="2" fill="{colour}"/></g>'
            )
        if i % label_every == 0:
            # The last label would be centred on the final column and run past
            # the canvas edge, so it anchors to the right instead.
            cx = x + bw / 2
            anchor = "middle"
            if cx + _text_width(name, AXIS_FONT) / 2 > width - 2:
                cx, anchor = width - 2, "end"
            parts.append(_axis_text(mode, cx, top + plot_h + 15, name, anchor,
                                    muted=True))
    parts.append(_grid_line(mode, left, top + plot_h, left + plot_w, top + plot_h))
    return "".join(parts)


# --- data preparation -----------------------------------------------------
def _territory_of(company: dict) -> str:
    return (company.get("countries") or company.get("regions") or "").split("; ")[0]


def _sector_of(company: dict) -> str:
    return (company.get("sectors") or "").split("; ")[0]


# The catalogue files a large residue under a heading that is a filing
# convention, not an industry. Counting it as the biggest "sector" would be
# the single most misleading bar in the set.
NON_SECTOR = "Documents généraux (par ordre chronologique)"


def gather(lang: str) -> dict:
    """Everything the ten figures need, in one pass over the tables."""
    comp = {c["company_id"]: c for c in read_csv("companies.csv")}
    edges = read_csv("edges_person_company.csv")
    cent = read_csv("company_centrality.csv")
    interlock = read_csv("edges_company_interlock.csv")
    pos_terr = read_csv("positionality_by_territory.csv")

    by_year: dict[str, Counter] = defaultdict(Counter)
    by_period: dict[str, Counter] = defaultdict(Counter)
    seats = Counter()
    firm_year: dict[tuple, set] = defaultdict(set)
    terr = Counter()
    sect = Counter()
    roles = Counter()
    for e in edges:
        g = e["source_genre"].split("; ")[0]
        if e["year"]:
            by_year[e["year"]][g] += 1
        if e["period"]:
            by_period[e["period"]][g] += 1
        roles[e["role"]] += 1
        if e["is_board_seat"] == "1":
            seats[e["person_id"]] += 1
            if e["year"]:
                firm_year[(e["company_id"], e["year"])].add(e["person_id"])
        c = comp.get(e["company_id"])
        if c:
            t = _territory_of(c)
            if t:
                terr[t] += 1
            s = _sector_of(c)
            if s and s != NON_SECTOR:
                sect[s] += 1
    return {
        "by_year": by_year, "by_period": by_period, "seats": seats,
        "board_size": Counter(len(v) for v in firm_year.values()),
        "terr": terr, "sect": sect, "roles": roles,
        "cent": cent, "interlock": interlock, "pos_terr": pos_terr,
        "n_edges": len(edges), "comp": comp,
    }


# --- the ten figures ------------------------------------------------------
def fig_ties_by_year(d, mode, lang):
    years = sorted(d["by_year"], key=int)
    groups = [(y, d["by_year"][y]) for y in years]
    keys = [g for g in GENRES if any(c.get(g) for _, c in groups)]
    body = stacked(groups, 1340, 470, mode, keys,
                   lambda k: GENRE_LABEL[lang][k], label_every=max(1, len(years) // 26))
    peak = max(groups, key=lambda g: sum(g[1].values()))
    total = sum(sum(c.values()) for _, c in groups)
    cap = {
        "fr": (f"Observations datées par année, empilées par genre de source. "
               f"{peak[0]} en concentre {_fmt(sum(peak[1].values()))}, "
               f"soit {sum(peak[1].values())/total:.0%} de toutes les observations datées : "
               f"un seul annuaire, dépouillé intégralement. Ce pic n'est pas un fait "
               f"historique, c'est la forme de la source."),
        "en": (f"Dated observations per year, stacked by source genre. "
               f"{peak[0]} alone holds {_fmt(sum(peak[1].values()))} of them, "
               f"{sum(peak[1].values())/total:.0%} of every dated observation, because one "
               f"annuaire was read end to end. The spike is the shape of the source, "
               f"not of the history."),
    }[lang]
    title = {"fr": "Observations par année et genre de source",
             "en": "Observations per year, by source genre"}[lang]
    legend = list(zip(series(mode, len(keys)), [GENRE_LABEL[lang][k] for k in keys]))
    tbl = ([H(lang, "year")] + [GENRE_LABEL[lang][k] for k in keys],
           [[y] + [d["by_year"][y].get(k, 0) for k in keys] for y in years])
    return body, 470, title, legend, cap, tbl


def fig_genre_by_period(d, mode, lang):
    groups = [(PERIOD_LABEL[name], d["by_period"][name]) for name, _, _ in PERIODS
              if d["by_period"].get(name)]
    keys = [g for g in GENRES if any(c.get(g) for _, c in groups)]
    body = stacked(groups, 1040, 400, mode, keys,
                   lambda k: GENRE_LABEL[lang][k], share=True)
    cap = {
        "fr": ("Part de chaque genre de source à l'intérieur de chaque période. "
               "L'index de personnes est entièrement contenu dans 1945–1962 : "
               "comparer deux périodes sans tenir le genre constant compare "
               "deux méthodes de dépouillement, pas deux époques."),
        "en": ("Share of each source genre within each period. The person index "
               "falls entirely inside 1945–1962, so comparing two periods without "
               "holding genre constant compares two ways of reading the archive "
               "rather than two eras."),
    }[lang]
    title = {"fr": "Composition des sources par période",
             "en": "Source composition within each period"}[lang]
    legend = list(zip(series(mode, len(keys)), [GENRE_LABEL[lang][k] for k in keys]))
    tbl = ([H(lang, "period")] + [GENRE_LABEL[lang][k] for k in keys],
           [[n] + [c.get(k, 0) for k in keys] for n, c in groups])
    return body, 400, title, legend, cap, tbl


def fig_seats_per_person(d, mode, lang):
    dist = Counter(d["seats"].values())
    top = max(dist)
    rows = [(str(k) if k % 5 == 0 or k == 1 else "", dist.get(k, 0),
             f"{_fmt(dist.get(k, 0))} × {k}") for k in range(1, min(top, 60) + 1)]
    body = columns(rows, 1040, 400, mode, log=True, label_every=1,
                   y_title={"fr": "personnes (log)", "en": "people (log)"}[lang],
                   x_title={"fr": "sièges détenus", "en": "board seats held"}[lang])
    total = sum(d["seats"].values())
    ordered = sorted(d["seats"].values(), reverse=True)
    share = sum(ordered[:max(1, len(ordered) // 100)]) / total
    cap = {
        "fr": (f"Nombre de sièges par personne. {_fmt(dist[1])} personnes n'en "
               f"détiennent qu'un seul ; le 1 % le mieux doté en détient {share:.0%}. "
               f"L'axe vertical est logarithmique — sur une échelle linéaire la "
               f"queue serait invisible."),
        "en": (f"Board seats per person. {_fmt(dist[1])} people hold exactly one; "
               f"the best-connected 1% hold {share:.0%} of all seats. The vertical "
               f"axis is logarithmic — on a linear one the tail would vanish."),
    }[lang]
    title = {"fr": "Concentration des mandats", "en": "Concentration of board seats"}[lang]
    tbl = ([H(lang, "seats"), H(lang, "people")],
           [[k, dist[k]] for k in sorted(dist)])
    return body, 400, title, None, cap, tbl


def fig_board_size(d, mode, lang):
    dist = d["board_size"]
    top = max(dist)
    rows = [(str(k) if k % 5 == 0 or k == 1 else "", dist.get(k, 0),
             f"{_fmt(dist.get(k, 0))} × {k}") for k in range(1, top + 1)]
    body = columns(rows, 1040, 380, mode, log=True,
                   y_title={"fr": "firmes-années (log)", "en": "firm-years (log)"}[lang],
                   x_title={"fr": "administrateurs observés", "en": "directors observed"}[lang])
    cap = {
        "fr": ("Administrateurs distincts observés pour une firme dans une année. "
               "La masse se situe entre 3 et 12, ce qu'un conseil d'administration "
               "réel permet ; la queue au-delà de 30 signale des notices où "
               "plusieurs firmes ont été fondues en une seule."),
        "en": ("Distinct directors observed for one firm in one year. The mass sits "
               "between 3 and 12, which is what a real board allows; the tail beyond "
               "30 marks notices where several firms were run together into one."),
    }[lang]
    title = {"fr": "Taille des conseils observés", "en": "Observed board sizes"}[lang]
    tbl = ([H(lang, "size"), H(lang, "fy")], [[k, dist[k]] for k in sorted(dist)])
    return body, 380, title, None, cap, tbl


def _ranked(counter, lang, kind, top_n=15):
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    head = items[:top_n]
    rest = sum(v for _, v in items[top_n:])
    rows = [(localise(k, lang, kind), v, f"{localise(k, lang, kind)}: {_fmt(v)}")
            for k, v in head]
    if rest:
        other = {"fr": "autres", "en": "other"}[lang]
        rows.append((f"{other} ({len(items) - top_n})", rest, f"{other}: {_fmt(rest)}"))
    return rows


def fig_ties_by_territory(d, mode, lang):
    rows = _ranked(d["terr"], lang, "territory")
    body, h = hbars(rows, 1040, mode, label_w=280.0)
    total = sum(d["terr"].values())
    top4 = sum(v for _, v, _ in rows[:4]) / total
    cap = {
        "fr": (f"Ties par territoire, la firme étant rattachée à son premier "
               f"territoire catalogué. Quatre territoires en concentrent {top4:.0%} : "
               f"l'absence d'une firme ailleurs renseigne sur la collecte, pas sur "
               f"l'économie coloniale."),
        "en": (f"Ties per territory, each firm assigned to the first territory it is "
               f"catalogued under. Four territories hold {top4:.0%} of them: a firm's "
               f"absence elsewhere is a fact about the collection, not about the "
               f"colonial economy."),
    }[lang]
    title = {"fr": "Ties par territoire", "en": "Ties by territory"}[lang]
    tbl = ([H(lang, "terr"), H(lang, "ties")], [[a, b] for a, b, _ in rows])
    return body, h + 8, title, None, cap, tbl


def fig_ties_by_sector(d, mode, lang):
    rows = _ranked(d["sect"], lang, "sector")
    body, h = hbars(rows, 1040, mode, label_w=300.0)
    cap = {
        "fr": ("Ties par secteur, tel que le classe la source. La rubrique "
               "« Documents généraux » est exclue : c'est une convention de "
               "classement, pas une industrie, et elle dominerait le graphique "
               "sans rien dire de l'économie."),
        "en": ("Ties per sector, as the source classifies them. The heading "
               "“Documents généraux” is excluded: it is a filing convention "
               "rather than an industry, and it would top the chart while saying "
               "nothing about the economy."),
    }[lang]
    title = {"fr": "Ties par secteur", "en": "Ties by sector"}[lang]
    tbl = ([H(lang, "sect"), H(lang, "ties")], [[a, b] for a, b, _ in rows])
    return body, h + 8, title, None, cap, tbl


ROLE_LABEL = {
    "fr": {"administrateur": "administrateur", "president": "président",
           "directeur": "directeur", "commissaire_aux_comptes": "commissaire aux comptes",
           "administrateur_delegue": "administrateur délégué",
           "vice_president": "vice-président", "gerant": "gérant",
           "president_directeur_general": "PDG", "censeur": "censeur",
           "directeur_general": "directeur général", "secretaire": "secrétaire",
           "conseil_surveillance": "conseil de surveillance",
           "liquidateur": "liquidateur", "fondateur": "fondateur",
           "ingenieur_conseil": "ingénieur-conseil"},
    "en": {"administrateur": "director", "president": "chairman",
           "directeur": "manager", "commissaire_aux_comptes": "auditor",
           "administrateur_delegue": "managing director",
           "vice_president": "vice-chairman", "gerant": "general partner",
           "president_directeur_general": "chairman & CEO", "censeur": "censor",
           "directeur_general": "general manager", "secretaire": "secretary",
           "conseil_surveillance": "supervisory board",
           "liquidateur": "liquidator", "fondateur": "founder",
           "ingenieur_conseil": "consulting engineer"},
}


def fig_roles(d, mode, lang):
    items = sorted(d["roles"].items(), key=lambda kv: (-kv[1], kv[0]))
    total = sum(d["roles"].values())
    rows = [(ROLE_LABEL[lang].get(k, k), v,
             f"{ROLE_LABEL[lang].get(k, k)}: {_fmt(v)} ({v/total:.1%})")
            for k, v in items]
    body, h = hbars(rows, 1040, mode, label_w=230.0)
    board = d["roles"]["administrateur"] / total
    cap = {
        "fr": (f"Rôles enregistrés. « administrateur » couvre {board:.0%} des ties : "
               f"c'est le rôle par défaut lorsqu'une liste ne précise rien, si bien "
               f"qu'il agrège les mandats réellement qualifiés et ceux qui ne le sont "
               f"pas. Les commissaires aux comptes ne sont pas des administrateurs et "
               f"sont exclus des projections d'interlocks."),
        "en": ("Recorded roles. “administrateur” covers "
               f"{board:.0%} of ties because it is the default when a list qualifies "
               f"nobody, so it pools genuinely qualified seats with unqualified ones. "
               f"Auditors are not directors and are excluded from the interlock "
               f"projection."),
    }[lang]
    title = {"fr": "Composition des rôles", "en": "Role composition"}[lang]
    tbl = ([H(lang, "role"), H(lang, "ties"), H(lang, "pct")],
           [[a, b, f"{b/total:.1%}"] for a, b, _ in rows])
    return body, h + 8, title, None, cap, tbl


def fig_positionality(d, mode, lang):
    rows_in = [r for r in d["pos_terr"] if int(r["n_board_members"] or 0) >= 60]
    rows_in.sort(key=lambda r: (-float(r["share_native"] or 0), r["territory"]))
    rows = [(localise(r["territory"], lang, "territory"),
             float(r["share_native"] or 0) * 100,
             f'{localise(r["territory"], lang, "territory")}: '
             f'{r["n_board_members"]} {"membres" if lang == "fr" else "members"}, '
             f'{float(r["share_native"] or 0):.1%}')
            for r in rows_in]
    body, h = hbars(rows, 1040, mode, label_w=300.0,
                    value_fmt=lambda v: f"{v:.1f}%".replace(".", "," if lang == "fr" else "."))
    zero = sum(1 for _, v, _ in rows if v == 0)
    cap = {
        "fr": (f"Part des administrateurs portant un nom indigène, pour les "
               f"territoires comptant au moins 60 membres de conseil. {zero} de ces "
               f"territoires sont à 0,0 %. Le codage est onomastique : il vaut pour "
               f"une composition d'ensemble, jamais pour un individu nommé."),
        "en": (f"Share of board members carrying an indigenous name, for territories "
               f"with at least 60 recorded members. {zero} of them sit at 0.0%. The "
               f"coding is onomastic: good for aggregate composition, never for a "
               f"claim about a named individual."),
    }[lang]
    title = {"fr": "Part indigène par territoire",
             "en": "Indigenous share by territory"}[lang]
    tbl = ([H(lang, "terr"), H(lang, "share")],
           [[a, f"{v:.1f}%"] for a, v, _ in rows])
    return body, h + 8, title, None, cap, tbl


def fig_brokers(d, mode, lang):
    """Brokers, as a ranking rather than a cloud.

    This began as a degree-rank against betweenness-rank scatter. On a shared
    scale — the only scale on which "distance from the diagonal" means anything
    — the top 400 by betweenness occupy a thin band across the top and nine
    tenths of the canvas is empty. The question is "which firms are brokers",
    which is a ranked comparison of one derived quantity, so it gets the form
    a ranked comparison gets.
    """
    rows_in = [r for r in d["cent"]
               if r.get("in_giant") == "1" and r.get("broker_gap")
               and int(r["betweenness_rank"]) <= 600]
    rows_in.sort(key=lambda r: (-int(r["broker_gap"]), r["name"]))
    top = rows_in[:18]
    deg = {"fr": "degré", "en": "degree"}[lang]
    btw = {"fr": "intermédiarité", "en": "betweenness"}[lang]
    rows = [(r["name"], int(r["broker_gap"]),
             f'{r["name"][:56]} · {deg} #{r["degree_rank"]} → {btw} #{r["betweenness_rank"]}')
            for r in top]
    body, h = hbars(rows, 1040, mode, label_w=330.0,
                    value_fmt=lambda v: f"+{_fmt(v)}")
    best = top[0]
    cap = {
        "fr": (f"Les 18 firmes dont le rang d'intermédiarité dépasse le plus "
               f"nettement leur rang de degré, parmi les 600 premières en "
               f"intermédiarité. La barre est l'écart entre les deux rangs. "
               f"{best['name'][:40]} gagne {_fmt(int(best['broker_gap']))} rangs : "
               f"peu de mandats partagés, mais placés entre des groupes qui ne se "
               f"touchent pas autrement. Un courtier n'est pas un carrefour. "
               f"« Agence centrale à PARIS » n'est pas une firme mais un libellé "
               f"mal découpé : un nœud parasite occupe une position structurale "
               f"réelle, ce qui est précisément la dette d'hygiène des noms de "
               f"sociétés que signale le codebook."),
        "en": (f"The 18 firms whose betweenness rank most exceeds their degree "
               f"rank, among the top 600 by betweenness. The bar is the gap "
               f"between the two ranks. {best['name'][:40]} gains "
               f"{_fmt(int(best['broker_gap']))} places: few shared "
               f"directorships, but placed between groups that otherwise do not "
               f"touch. A broker is not a hub. “Agence centrale à PARIS” is not a "
               f"firm but a mis-cut field label: a junk node holding a real "
               f"structural position, which is exactly the company-name hygiene "
               f"debt the codebook flags."),
    }[lang]
    title = {"fr": "Courtiers : rang gagné en intermédiarité",
             "en": "Brokers: rank gained on betweenness"}[lang]
    tbl = ([H(lang, "firm"), H(lang, "gap")],
           [[r["name"], int(r["broker_gap"])] for r in top])
    return body, h + 8, title, None, cap, tbl


def fig_interlock_weight(d, mode, lang):
    dist = Counter(int(e["weight"]) for e in d["interlock"])
    top = max(dist)
    rows = [(str(k) if k % 5 == 0 or k == 1 else "", dist.get(k, 0),
             f"{_fmt(dist.get(k, 0))} × {k}") for k in range(1, top + 1)]
    body = columns(rows, 1040, 380, mode, log=True,
                   y_title={"fr": "liens (log)", "en": "edges (log)"}[lang],
                   x_title={"fr": "administrateurs partagés",
                            "en": "shared directors"}[lang])
    total = sum(dist.values())
    one = dist[1] / total
    cap = {
        "fr": (f"Nombre d'administrateurs partagés par lien d'interlock. "
               f"{one:.0%} des liens ne reposent que sur une seule personne : "
               f"une erreur de résolution d'entité sur ce nom fait disparaître le "
               f"lien. Filtrer à poids ≥ 2 donne un graphe bien plus robuste."),
        "en": (f"Shared directors per interlock edge. {one:.0%} of edges rest on a "
               f"single person, so one entity-resolution error on that name removes "
               f"the edge entirely. Filtering to weight ≥ 2 gives a far more robust "
               f"graph."),
    }[lang]
    title = {"fr": "Robustesse des liens d'interlock",
             "en": "How much each interlock rests on"}[lang]
    tbl = ([H(lang, "w"), H(lang, "edges")], [[k, dist[k]] for k in sorted(dist)])
    return body, 380, title, None, cap, tbl


FIGURES = [
    ("fig8_ties_by_year", fig_ties_by_year, 1340.0),
    ("fig9_genre_by_period", fig_genre_by_period, 1040.0),
    ("fig10_seats_per_person", fig_seats_per_person, 1040.0),
    ("fig11_board_size", fig_board_size, 1040.0),
    ("fig12_ties_by_territory", fig_ties_by_territory, 1040.0),
    ("fig13_ties_by_sector", fig_ties_by_sector, 1040.0),
    ("fig14_roles", fig_roles, 1040.0),
    ("fig15_positionality", fig_positionality, 1040.0),
    ("fig16_brokers_vs_hubs", fig_brokers, 1040.0),
    ("fig17_interlock_weight", fig_interlock_weight, 1040.0),
]



# --- the page -------------------------------------------------------------
# Three of the light-mode categorical slots sit below 3:1 on the light surface,
# so the palette's relief rule applies: the figures must ship a table view, not
# offer one. Every figure below therefore carries its numbers in a <details>
# table underneath, and the page defines both themes from the same ramps rather
# than flipping the light one.
PAGE_CSS = """
:root { --surface:#fcfcfb; --text-primary:#0b0b0b; --text-secondary:#52514e;
  --text-muted:#8a8983; --hairline:#e6e5e1;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4;
  --other:#a9a8a2; --edge:#c9c8c2;
  --land:#f1f0ec; --coast:#d5d4ce; --graticule:#e9e8e4; }
@media (prefers-color-scheme: dark) { :root:where(:not([data-theme=light])) {
  --surface:#1a1a19; --text-primary:#fff; --text-secondary:#c3c2b7;
  --text-muted:#8a8983; --hairline:#33332f;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
  --other:#6f6e69; --edge:#3d3d39;
  --land:#242423; --coast:#403f3a; --graticule:#2b2b28; } }
:root[data-theme=dark] { --surface:#1a1a19; --text-primary:#fff;
  --text-secondary:#c3c2b7; --text-muted:#8a8983; --hairline:#33332f;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
  --other:#6f6e69; --edge:#3d3d39;
  --land:#242423; --coast:#403f3a; --graticule:#2b2b28; }
* { box-sizing:border-box }
body { margin:0; padding:28px clamp(14px,4vw,56px); background:var(--surface);
  color:var(--text-primary); font:15px/1.55 ui-sans-serif,system-ui,sans-serif; }
h1 { font-size:23px; margin:0 0 6px }
p.lede { color:var(--text-secondary); max-width:72ch; margin:0 0 26px }
figure { margin:0 0 40px; border-top:1px solid var(--hairline); padding-top:18px }
figcaption { color:var(--text-secondary); font-size:13.5px; max-width:88ch; margin:2px 0 12px }
svg { max-width:100%; height:auto; display:block }
.mk:hover circle, .mk:hover rect { filter:brightness(1.12) }
details { margin-top:12px }
summary { cursor:pointer; color:var(--text-secondary); font-size:13px }
table { border-collapse:collapse; margin-top:10px; font-size:13px }
th,td { text-align:left; padding:3px 16px 3px 0; border-bottom:1px solid var(--hairline) }
td.num,th.num { text-align:right }
button { font:inherit; font-size:13px; color:var(--text-secondary);
  background:none; border:1px solid var(--hairline); border-radius:7px;
  padding:5px 11px; cursor:pointer; margin-bottom:22px }
"""


def _table_html(table, lang):
    if not table:
        return ""
    headers, rows = table
    label = {"fr": "Voir les données", "en": "Show the data"}[lang]
    head = "".join(f'<th class="num">{esc(h)}</th>' if i else f"<th>{esc(h)}</th>"
                   for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(
            f'<td class="num">{esc(str(c))}</td>' if i else f"<td>{esc(str(c))}</td>"
            for i, c in enumerate(r)) + "</tr>"
        for r in rows)
    return (f"<details><summary>{esc(label)}</summary>"
            f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
            f"</details>")


def render_page(d, lang: str) -> str:
    title = {"fr": "Le jeu de données, en dix figures",
             "en": "The dataset, in ten figures"}[lang]
    lede = {
        "fr": ("Ce que les diagrammes de réseau ne montrent pas : quand les "
               "observations ont été faites, où la couverture est mince, et ce "
               "sur quoi repose chaque lien. À lire avant toute mesure de "
               "centralité."),
        "en": ("What the network diagrams cannot show: when the observations were "
               "made, where the coverage is thin, and what each edge actually "
               "rests on. Read this before computing any centrality."),
    }[lang]
    toggle = {"fr": "Basculer le thème", "en": "Toggle theme"}[lang]
    out = [
        "<!doctype html><html lang=\"" + lang + "\"><meta charset=\"utf-8\">",
        f"<title>{esc(title)}</title>",
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<style>{PAGE_CSS}</style>",
        f"<h1>{esc(title)}</h1><p class=\"lede\">{esc(lede)}</p>",
        f'<button onclick="document.documentElement.dataset.theme='
        f'document.documentElement.dataset.theme===\'dark\'?\'light\':\'dark\'">'
        f'{esc(toggle)}</button>',
    ]
    for name, fn, width in FIGURES:
        body, height, ftitle, legend, caption, table = fn(d, "vars", lang)
        svg = svg_document(body, width, height, "vars", ftitle,
                           legend=legend, caption="")
        out.append(
            f'<figure id="{name}"><h2 style="font-size:16px;margin:0 0 2px">'
            f'{esc(ftitle)}</h2>'
            f'<figcaption>{esc(caption)}</figcaption>{svg}'
            f'{_table_html(table, lang)}</figure>'
        )
    out.append("</html>")
    return "".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=LANGS, default="fr")
    args = ap.parse_args()
    out_dir = FIG_DIR if args.lang == "fr" else os.path.join(FIG_DIR, args.lang)
    ensure_dir(out_dir)

    d = gather(args.lang)
    for name, fn, width in FIGURES:
        body, height, title, legend, caption, _ = fn(d, "light", args.lang)
        svg = svg_document(body, width, height, "light", title,
                           legend=legend, caption=caption)
        with open(os.path.join(out_dir, f"{name}.svg"), "w", encoding="utf-8") as fh:
            fh.write(svg)
    page_path = os.path.join(out_dir, "descriptive.html")
    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write(render_page(d, args.lang))
    print(f"wrote {len(FIGURES)} descriptive figures + descriptive.html to "
          f"{os.path.relpath(out_dir, os.path.dirname(FIG_DIR))}", file=sys.stderr)


if __name__ == "__main__":
    main()
