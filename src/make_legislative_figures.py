"""Stage 15 - the legislative elite, in six figures.

    python3 src/make_legislative_figures.py            # -> figures/fig34..39
    python3 src/make_legislative_figures.py --lang en

The question these answer is continuity: not "were parliamentarians on colonial
boards" - the compiler assembled five directories to prove they were - but
*which kind* of continuity the record actually supports. Three kinds get
confused, and each figure here is built to isolate one of them.

- **fig34, terms.** One man's own run. Horizontal spans, one row per
  parliamentarian with a dated term, sorted by first year. Reads as a
  generational chart: where the rows overlap vertically, a cohort sat together.
- **fig35, the census.** Whether the *same* man is in the next directory.
  Five snapshot columns, one row per man, ordered by first appearance, so
  persistence is a horizontal run and turnover is a gap. The transition
  numbers sit under it because the eye reads the block and not the churn.
- **fig36, who sat with whom.** The legislator-legislator graph, node level,
  named, edges weighted by boards shared. Colour is the chamber - two slots,
  and the third is never used, because a third chamber does not exist.
- **fig37, the firms.** Which boards carried the most parliamentarians. A
  ranked magnitude with long labels, so bars.
- **fig38, seat against territory.** Whether a metropolitan constituency
  predicts which colony's board its deputy sat on. A two-mode arc diagram:
  seats on the left, territories on the right.
- **fig39, direct against proxy.** The compiler's own distinction - held
  personally, or held through a relative - by snapshot.

**Why no bump chart, no sankey, no chord.** All three encode flow between
ordered categories, and what the snapshots record is presence in a census
whose gaps are as often the compiler's silence as a man's departure. A ribbon
drawn between 1936 and 1954 would assert a continuous quantity across an
eighteen-year hole that also spans a change of republic. The presence grid
states what is known - present, absent - and leaves the reader to see that the
1936-1954 pair carries almost no one across.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import draw  # noqa: E402
from common import ensure_dir  # noqa: E402
from labels import LANGS, localise  # noqa: E402
from make_descriptive_figures import (PAGE_CSS, _axis_text, _fmt,  # noqa: E402
                                      _table_html, hbars)
from make_figures import (PALETTE, FIG_DIR, esc, svg_document,  # noqa: E402
                          trim_to_width)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")

W = 1340.0
SNAPSHOTS = ["1924", "1930", "1932", "1936", "1954"]
SPAN_ROWS = 46          # men shown in the term chart
GRID_ROWS = 60          # men shown in the presence grid
NET_NODES = 42          # legislators drawn in the interlock graph
TOP_FIRMS = 16
TOP_SEATS = 13
TOP_TERR = 8
CHAMBER_SLOT = {"Chamber of Deputies": 0, "Senate": 1}
AXIS_FONT = 10.5
MAX_SPAN = 55           # longest plausible parliamentary run, in years


def load(name: str) -> list[dict]:
    path = os.path.join(PROC, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def gather() -> dict:
    legs = load("legislators.csv")
    return {
        "legislators": legs,
        "by_id": {r["person_id"]: r for r in legs},
        "edges": load("edges_legislator_interlock.csv"),
        "continuity": load("legislative_continuity.csv"),
        "roster": load("roster_mandates.csv"),
        "roster_ties": load("affiliations_roster.csv"),
        "companies": {c["company_id"]: c for c in load("companies.csv")},
        "ties": load("edges_person_company.csv"),
    }


def _chamber(rec: dict) -> str:
    """The single chamber a row is drawn under. Both -> the Senate.

    A man who moved from the Chamber to the Senate is drawn as a senator
    because that is where his run ended; `both_chambers` carries the fact, and
    fig34 marks those rows so the movement is not lost.
    """
    chambers = (rec.get("chambers") or "").split("; ")
    return "Senate" if "Senate" in chambers else (chambers[0] or "")


def _colour(chamber: str, mode: str) -> str:
    p = PALETTE[mode]
    slot = CHAMBER_SLOT.get(chamber)
    return p["series"][slot] if slot is not None else p["other"]


def _chamber_label(chamber: str, lang: str) -> str:
    return {
        "Chamber of Deputies": {"fr": "Chambre des députés",
                                "en": "Chamber of Deputies"},
        "Senate": {"fr": "Sénat", "en": "Senate"},
    }.get(chamber, {"fr": "inconnu", "en": "unknown"})[lang]


# --- fig34: mandate terms -------------------------------------------------
def fig_terms(d, mode, lang):
    p = PALETTE[mode]
    # Two filters, both about key collision rather than taste. A person key
    # built from a surname alone - "Picot", "Lederlin" - merges every man of
    # that name in the corpus, and the pooled first and last year then span
    # three generations. Requiring a forename removes most of those, and a
    # span longer than MAX_SPAN removes the rest: no one sat for 78 years, so a
    # bar that says so is two men.
    rows = [r for r in d["legislators"]
            if _int(r["first_year"]) and _int(r["last_year"])
            and _int(r["last_year"]) > _int(r["first_year"])
            and _int(r["last_year"]) - _int(r["first_year"]) <= MAX_SPAN
            and len(r["name_clean"].split()) >= 2
            and r["in_network"] == "1"]
    rows.sort(key=lambda r: (_int(r["first_year"]), -int(r["n_companies"]),
                             r["name_clean"]))
    shown = rows[:SPAN_ROWS]
    if not shown:
        return "", 40.0, "", None, "", None

    lo = min(_int(r["first_year"]) for r in shown)
    hi = max(_int(r["last_year"]) for r in shown)
    label_w, right, row_h, top = 214.0, 96.0, 15.0, 26.0
    plot_w = W - label_w - right
    height = top + len(shown) * row_h + 30.0

    def x_of(year):
        return label_w + plot_w * (year - lo) / max(hi - lo, 1)

    parts = []
    # Decade gridlines, recessive, behind everything.
    for year in range(lo - lo % 10, hi + 1, 10):
        if year < lo:
            continue
        gx = x_of(year)
        parts.append(f'<line x1="{gx:.1f}" y1="{top - 8:.1f}" x2="{gx:.1f}" '
                     f'y2="{height - 26:.1f}" stroke="{p["hairline"]}" '
                     f'stroke-width="1"/>')
        parts.append(_axis_text(mode, gx, height - 12, str(year), "middle",
                                AXIS_FONT, muted=True))

    for i, r in enumerate(shown):
        a, b = _int(r["first_year"]), _int(r["last_year"])
        y = top + i * row_h
        cy = y + row_h / 2
        x0, x1 = x_of(a), x_of(b)
        colour = _colour(_chamber(r), mode)
        name = r["name_clean"]
        if r["both_chambers"] == "1":
            name += " ·"
        tip = (f"{r['name_clean']} — {_chamber_label(_chamber(r), lang)}"
               f", {r['constituencies'] or '?'} ({a}–{b}), "
               f"{r['n_companies']} " + ("sociétés" if lang == "fr"
                                         else "companies"))
        parts.append(
            f'<g class="mk"><title>{esc(tip)}</title>'
            f'{_axis_text(mode, label_w - 9, cy + 3.6, trim_to_width(name, AXIS_FONT, label_w - 14), "end")}'
            f'<rect x="{x0:.1f}" y="{y + 3.4:.1f}" '
            f'width="{max(x1 - x0, 3.0):.1f}" height="{row_h - 7.8:.1f}" '
            f'rx="3" fill="{colour}"/>'
            f'{_axis_text(mode, x1 + 7, cy + 3.6, f"{a}–{b}", "start", AXIS_FONT, muted=True)}'
            f'</g>')

    title = {"fr": "fig. 34 — Les mandats, dans le temps",
             "en": "fig. 34 — Terms of office, over time"}[lang]
    caption = {
        "fr": ("Un homme par ligne, parmi ceux dont le mandat est daté et qui "
               "siègent à un conseil colonial ; classés par première année. "
               "Le point après un nom signale un passage de la Chambre au "
               "Sénat. La longueur de la barre est la durée connue, non la "
               "durée réelle : le compilateur donne un intervalle, pas un "
               "relevé de législature. Les clés construites sur un seul nom "
               "de famille sont écartées, ainsi que les intervalles de plus "
               f"de {MAX_SPAN} ans : ce sont des homonymes fondus en un."),
        "en": ("One man per row, among those whose term is dated and who sat "
               "on a colonial board; ordered by first year. A dot after a name "
               "marks a move from the Chamber to the Senate. Bar length is the "
               "*known* span, not the true one: the compiler gives an "
               "interval, not a parliamentary record. Keys built from a "
               "surname alone are excluded, as are spans longer than "
               f"{MAX_SPAN} years: those are namesakes merged into one."),
    }[lang]
    legend = [(p["series"][0], _chamber_label("Chamber of Deputies", lang)),
              (p["series"][1], _chamber_label("Senate", lang))]
    table = (
        [{"fr": "Nom", "en": "Name"}[lang],
         {"fr": "Chambre", "en": "Chamber"}[lang],
         {"fr": "Circonscription", "en": "Constituency"}[lang],
         {"fr": "De", "en": "From"}[lang], {"fr": "À", "en": "To"}[lang],
         {"fr": "Sociétés", "en": "Companies"}[lang]],
        [(r["name_clean"], _chamber_label(_chamber(r), lang),
          r["constituencies"], r["first_year"], r["last_year"],
          r["n_companies"]) for r in shown],
    )
    return "".join(parts), height, title, legend, caption, table


# --- fig35: the presence grid --------------------------------------------
def fig_presence(d, mode, lang):
    p = PALETTE[mode]
    present = collections.defaultdict(set)
    for row in d["roster"]:
        if row["snapshot_year"] in SNAPSHOTS:
            present[row["person_key"]].add(row["snapshot_year"])
    # Order by first appearance, then by how many snapshots, then by name, so
    # the long runs rise to the top of each entry cohort.
    people = sorted(
        present.items(),
        key=lambda kv: (SNAPSHOTS.index(min(kv[1], key=SNAPSHOTS.index)),
                        -len(kv[1]), kv[0]))
    names = {}
    for row in d["roster"]:
        names.setdefault(row["person_key"], row["name_clean"])
    shown = [kv for kv in people if len(kv[1]) >= 2][:GRID_ROWS]
    if not shown:
        return "", 40.0, "", None, "", None

    label_w, row_h, top = 214.0, 13.0, 40.0
    col_w = 108.0
    height = top + len(shown) * row_h + 96.0
    parts = []
    for j, year in enumerate(SNAPSHOTS):
        cx = label_w + col_w * (j + 0.5)
        parts.append(_axis_text(mode, cx, top - 12, year, "middle", AXIS_FONT))
    for i, (key, years) in enumerate(shown):
        y = top + i * row_h
        cy = y + row_h / 2
        parts.append(_axis_text(
            mode, label_w - 9, cy + 3.4,
            trim_to_width(names.get(key, key), AXIS_FONT, label_w - 14), "end"))
        span = [SNAPSHOTS.index(v) for v in years]
        # The connector runs between first and last appearance and is drawn
        # under the cells, so a gap in the middle stays visible as a gap.
        x0 = label_w + col_w * (min(span) + 0.5)
        x1 = label_w + col_w * (max(span) + 0.5)
        parts.append(f'<line x1="{x0:.1f}" y1="{cy:.1f}" x2="{x1:.1f}" '
                     f'y2="{cy:.1f}" stroke="{p["edge"]}" stroke-width="2"/>')
        for j, year in enumerate(SNAPSHOTS):
            cx = label_w + col_w * (j + 0.5)
            if year in years:
                parts.append(
                    f'<g class="mk"><title>{esc(names.get(key, key))} — '
                    f'{year}</title><rect x="{cx - 26:.1f}" '
                    f'y="{y + 2.6:.1f}" width="52" height="{row_h - 5.2:.1f}" '
                    f'rx="3" fill="{p["series"][0]}"/></g>')
            else:
                # The absent-cell dot is a mark, so it takes a mark token:
                # `text_muted` is ink a reader reads, not ink a reader
                # measures, and checks.py polices the difference.
                parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="1.6" '
                             f'fill="{p["other"]}"/>')

    # The transition numbers, as a strip under the grid.
    y0 = top + len(shown) * row_h + 26.0
    heads = {"fr": ["présents", "entrent", "restent", "sortent", "reconduits"],
             "en": ["present", "entered", "stayed", "left", "carryover"]}[lang]
    parts.append(_axis_text(mode, label_w - 9, y0, heads[0], "end", AXIS_FONT,
                            muted=True))
    keys = ["n_present", "n_entered", "n_stayed", "n_left", "carryover_rate"]
    for k, (label, key) in enumerate(zip(heads, keys)):
        yy = y0 + k * 13.0
        parts.append(_axis_text(mode, label_w - 9, yy, label, "end", AXIS_FONT,
                                muted=True))
        for j, year in enumerate(SNAPSHOTS):
            row = next((c for c in d["continuity"]
                        if c["snapshot_year"] == year), {})
            val = row.get(key, "")
            parts.append(_axis_text(mode, label_w + col_w * (j + 0.5),
                                    yy, val or "—", "middle", AXIS_FONT))
    height = y0 + len(keys) * 13.0 + 10.0

    title = {"fr": "fig. 35 — Le même homme, six ans plus tard",
             "en": "fig. 35 — The same man, six years later"}[lang]
    caption = {
        "fr": ("Les cinq annuaires du compilateur, une ligne par "
               "parlementaire présent dans au moins deux. Une case pleine : "
               "présent. Un point : absent de ce volume — ce qui peut vouloir "
               "dire qu'il n'était plus au Parlement, qu'il avait quitté ses "
               "conseils, ou que le compilateur ne l'a pas retrouvé. Le "
               "report 1936→1954 est proche de zéro : entre les deux, une "
               "guerre et une République."),
        "en": ("The compiler's five directories, one row per parliamentarian "
               "present in at least two. A filled cell: present. A dot: absent "
               "from that volume — which may mean he had left Parliament, left "
               "his boards, or that the compiler did not find him. Carryover "
               "from 1936 to 1954 is near zero: a war and a republic fall "
               "between them."),
    }[lang]
    table = (
        [{"fr": "Année", "en": "Year"}[lang]] + heads,
        [(c["snapshot_year"], c["n_present"], c["n_entered"], c["n_stayed"],
          c["n_left"], c["carryover_rate"] or "—") for c in d["continuity"]],
    )
    return "".join(parts), height, title, None, caption, table


# --- fig36: who sat with whom --------------------------------------------
def fig_interlock(d, mode, lang):
    p = PALETTE[mode]
    edges = [e for e in d["edges"] if e["source"] in d["by_id"]
             and e["target"] in d["by_id"]]
    if not edges:
        return "", 40.0, "", None, "", None
    strength = collections.Counter()
    for e in edges:
        strength[e["source"]] += int(e["weight"])
        strength[e["target"]] += int(e["weight"])
    keep = [k for k, _ in sorted(strength.items(),
                                 key=lambda kv: (-kv[1], kv[0]))[:NET_NODES]]
    keep_set = set(keep)
    drawn = sorted((e for e in edges
                    if e["source"] in keep_set and e["target"] in keep_set),
                   key=lambda e: (-int(e["weight"]), e["source"], e["target"]))

    # A ring, ordered by chamber then by strength, so the two chambers occupy
    # two arcs and a cross-chamber edge crosses the middle. A force layout
    # would put the same information nowhere in particular.
    order = sorted(keep, key=lambda k: (
        CHAMBER_SLOT.get(_chamber(d["by_id"][k]), 9), -strength[k], k))
    # An ellipse, not a circle: a circle of radius 258 on a 1340-wide canvas
    # leaves a third of it empty, and the ordering the ring encodes survives
    # the horizontal stretch unchanged.
    cx, cy, radius = W / 2, 352.0, 268.0
    pos = {k: (cx + (x - cx) * 1.52, y)
           for k, (x, y) in draw.ring_layout([(0, order)], cx, cy,
                                             [radius]).items()}
    hi = max(strength.values()) or 1
    nodes = []
    for k in order:
        rec = d["by_id"][k]
        x, y = pos[k]
        nodes.append({
            "id": k, "x": x, "y": y,
            "r": draw.area_radius(strength[k], hi, 11.0, 3.4),
            "color": _colour(_chamber(rec), mode),
            "label": rec["name_clean"],
            "tip": (f"{rec['name_clean']} — "
                    f"{_chamber_label(_chamber(rec), lang)}, "
                    f"{rec['constituencies'] or '?'}; "
                    f"{rec['n_companies']} "
                    + ("sociétés" if lang == "fr" else "companies")),
        })
    by_id = {n["id"]: n for n in nodes}
    segments = [((by_id[e["source"]]["x"], by_id[e["source"]]["y"]),
                 (by_id[e["target"]]["x"], by_id[e["target"]]["y"]), e)
                for e in drawn]
    body = [draw.curved_edges(
        segments, mode, bow=0.22,
        width_of=lambda e: min(1.0 + 0.7 * int(e["weight"]), 4.2),
        opacity_of=lambda e: 0.5 if e["same_chamber"] == "1" else 0.78,
        colour_of=lambda e: (p["edge"] if e["same_chamber"] == "1"
                             else p["other"]))]
    body.append(draw.hoverable(nodes, mode))
    for n, x, y, anchor in draw.place_labels(
            sorted(nodes, key=lambda n: -n["r"]), W, 700.0, max_width=168.0):
        body.append(draw.halo_text(mode, x, y, n["label"], anchor))

    title = {"fr": "fig. 36 — Qui a siégé avec qui",
             "en": "fig. 36 — Who sat with whom"}[lang]
    caption = {
        "fr": (f"Les {len(keep)} parlementaires les plus liés, par conseils "
               f"partagés. Anneau ordonné par chambre : les députés sur un "
               f"arc, les sénateurs sur l'autre, si bien qu'un lien "
               f"inter-chambres traverse le centre. L'épaisseur est le nombre "
               f"de conseils communs ; l'aire du nœud, le total. Un lien ne "
               f"dit pas que les deux hommes y ont siégé la même année : sur "
               f"{len(d['edges'])} paires, "
               f"{sum(1 for e in d['edges'] if e['mandates_overlap'] == '1')} "
               f"ont des mandats qui se recouvrent de façon vérifiable et "
               f"{sum(1 for e in d['edges'] if e['mandates_overlap'] == '')} "
               f"sont indéterminées."),
        "en": (f"The {len(keep)} most connected parliamentarians, by boards "
               f"shared. The ring is ordered by chamber — deputies on one arc, "
               f"senators on the other — so a cross-chamber tie crosses the "
               f"middle. Edge width is the number of shared boards; node area "
               f"is the total. An edge does not say the two men sat in the same "
               f"year: of {len(d['edges'])} pairs, "
               f"{sum(1 for e in d['edges'] if e['mandates_overlap'] == '1')} "
               f"have verifiably overlapping terms and "
               f"{sum(1 for e in d['edges'] if e['mandates_overlap'] == '')} "
               f"are undetermined."),
    }[lang]
    legend = [(p["series"][0], _chamber_label("Chamber of Deputies", lang)),
              (p["series"][1], _chamber_label("Senate", lang)),
              (p["other"], {"fr": "lien inter-chambres",
                            "en": "cross-chamber tie"}[lang])]
    table = (
        [{"fr": "Parlementaire", "en": "Parliamentarian"}[lang],
         {"fr": "Parlementaire", "en": "Parliamentarian"}[lang],
         {"fr": "Conseils", "en": "Boards"}[lang],
         {"fr": "Mandats concomitants", "en": "Terms overlap"}[lang]],
        [(e["source_name"], e["target_name"], e["weight"],
          {"1": {"fr": "oui", "en": "yes"}[lang],
           "0": {"fr": "non", "en": "no"}[lang],
           "": "—"}[e["mandates_overlap"]]) for e in drawn[:40]],
    )
    return "".join(body), 704.0, title, legend, caption, table


# --- fig37: the firms ----------------------------------------------------
def fig_firms(d, mode, lang):
    legs = {r["person_id"] for r in d["legislators"]
            if r["in_network"] == "1" and r["key_ambiguous"] == "0"}
    per_firm = collections.defaultdict(set)
    for row in d["ties"]:
        if row["person_id"] in legs:
            per_firm[row["company_id"]].add(row["person_id"])
    ranked = sorted(per_firm.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    rows = []
    for firm, members in ranked[:TOP_FIRMS]:
        c = d["companies"].get(firm, {})
        name = c.get("name") or firm
        terr = localise((c.get("countries") or "").split("; ")[0],
                        lang) or "—"
        rows.append((name, len(members), f"{name} — {terr}: {len(members)} "
                     + ("parlementaires" if lang == "fr"
                        else "parliamentarians")))
    if not rows:
        return "", 40.0, "", None, "", None
    body, height = hbars(rows, W, mode, label_w=400.0, row_h=26.0)
    title = {"fr": "fig. 37 — Les conseils les plus parlementaires",
             "en": "fig. 37 — The most parliamentary boards"}[lang]
    caption = {
        "fr": ("Nombre de parlementaires distincts siégeant au conseil, toutes "
               "années confondues. Un total élevé peut vouloir dire un accès "
               "continu ou une succession rapide : la figure ne les distingue "
               "pas, et fig. 35 montre pourquoi la distinction compte. Deux "
               "lignes portent un titre d'article et non un nom de société — "
               "« Les poursuites contre les dirigeants de la Banque "
               "industrielle de Chine » est la même firme que « La Banque "
               "industrielle de Chine ». C'est un défaut connu du registre "
               "des sociétés, recensé dans "
               "`company_duplicate_candidates.csv` et laissé visible ici "
               "plutôt que corrigé en silence."),
        "en": ("Distinct parliamentarians on the board, all years pooled. A "
               "high total can mean continuous access or rapid succession; "
               "this figure does not separate them, and fig. 35 shows why the "
               "distinction matters. Two rows carry an article title rather "
               "than a company name — « Les poursuites contre les dirigeants "
               "de la Banque industrielle de Chine » is the same firm as « La "
               "Banque industrielle de Chine ». That is a known defect of the "
               "company register, listed in "
               "`company_duplicate_candidates.csv`, and left visible here "
               "rather than quietly patched."),
    }[lang]
    table = (
        [{"fr": "Société", "en": "Company"}[lang],
         {"fr": "Territoire", "en": "Territory"}[lang],
         {"fr": "Parlementaires", "en": "Parliamentarians"}[lang]],
        [(d["companies"].get(f, {}).get("name") or f,
          localise((d["companies"].get(f, {}).get("countries")
                    or "").split("; ")[0], lang) or "—",
          len(m)) for f, m in ranked[:TOP_FIRMS]],
    )
    return body, height, title, None, caption, table


# --- fig38: seat against territory ---------------------------------------
def fig_seat_territory(d, mode, lang):
    p = PALETTE[mode]
    flows = collections.Counter()
    for r in d["legislators"]:
        if r["in_network"] != "1" or r["key_ambiguous"] == "1" \
                or not r["constituencies"]:
            continue
        seat = r["constituencies"].split("; ")[0]
        for terr in (r["territories"] or "").split("; "):
            if terr:
                flows[(seat, localise(terr, lang))] += 1
    if not flows:
        return "", 40.0, "", None, "", None
    seat_tot = collections.Counter()
    terr_tot = collections.Counter()
    for (s, t), n in flows.items():
        seat_tot[s] += n
        terr_tot[t] += n
    seats = [s for s, _ in seat_tot.most_common(TOP_SEATS)]
    terrs = [t for t, _ in terr_tot.most_common(TOP_TERR)]
    pairs = sorted(((s, t, n) for (s, t), n in flows.items()
                    if s in seats and t in terrs),
                   key=lambda x: (-x[2], x[0], x[1]))
    if not pairs:
        return "", 40.0, "", None, "", None

    left_x, right_x, top, bottom = 300.0, W - 300.0, 40.0, 470.0
    pos = draw.column_layout(seats, terrs, left_x, right_x, top, bottom)
    hi = max(n for _, _, n in pairs)
    nodes = []
    for ids, side in ((seats, "seat"), (terrs, "terr")):
        for i in ids:
            x, y = pos[i]
            tot = seat_tot[i] if side == "seat" else terr_tot[i]
            nodes.append({
                "id": f"{side}:{i}", "x": x, "y": y,
                "r": draw.area_radius(tot, max(seat_tot.values()), 9.0, 3.0),
                "color": p["series"][0] if side == "seat" else p["series"][2],
                "label": i,
                "tip": f"{i}: {tot}",
            })
    by_id = {n["id"]: n for n in nodes}
    segments = [((by_id[f"seat:{s}"]["x"], by_id[f"seat:{s}"]["y"]),
                 (by_id[f"terr:{t}"]["x"], by_id[f"terr:{t}"]["y"]), n)
                for s, t, n in pairs]
    body = [draw.curved_edges(
        segments, mode, bow=0.06,
        width_of=lambda n: 1.0 + 3.2 * n / hi,
        opacity_of=lambda n: 0.34 + 0.4 * n / hi,
        colour_of=lambda n: p["edge"])]
    body.append(draw.hoverable(nodes, mode))
    for n in nodes:
        side = n["id"].split(":")[0]
        x = n["x"] - n["r"] - 6 if side == "seat" else n["x"] + n["r"] + 6
        anchor = "end" if side == "seat" else "start"
        body.append(draw.halo_text(mode, x, n["y"] + 3.4,
                                   trim_to_width(n["label"], 10.5, 270.0),
                                   anchor))
    body.append(_axis_text(mode, left_x, top - 20,
                           {"fr": "Circonscription",
                            "en": "Constituency"}[lang], "middle", AXIS_FONT))
    body.append(_axis_text(mode, right_x, top - 20,
                           {"fr": "Territoire de la société",
                            "en": "Company territory"}[lang], "middle",
                           AXIS_FONT))

    title = {"fr": "fig. 38 — La circonscription et la colonie",
             "en": "fig. 38 — The constituency and the colony"}[lang]
    density = len(pairs) / (len(seats) * len(terrs))
    caption = {
        "fr": (f"À gauche, les circonscriptions qui envoient le plus de "
               f"parlementaires-administrateurs ; à droite, les territoires où "
               f"sont leurs sociétés. Le graphe est presque complet : "
               f"{len(pairs)} des {len(seats) * len(terrs)} paires possibles "
               f"({density:.0%}). La circonscription ne prédit pas la "
               f"colonie. C'est la conclusion, et non un défaut du dessin. La "
               f"Seine domine parce que c'est là que siégeaient les conseils, "
               f"non parce que ses électeurs étaient coloniaux ; les "
               f"circonscriptions coloniales — Alger, Cochinchine, Réunion — "
               f"se lisent autrement, le député y étant élu et administrant "
               f"sur place."),
        "en": (f"Left: the constituencies that send the most "
               f"parliamentarian-directors. Right: where their companies "
               f"were. The graph is close to complete: {len(pairs)} of "
               f"{len(seats) * len(terrs)} possible pairs ({density:.0%}). "
               f"The constituency does not predict the colony. That is the "
               f"finding, not a failure of the drawing. The Seine dominates "
               f"because that is where the boards met, not because its voters "
               f"were colonial; the colonial constituencies — Alger, "
               f"Cochinchina, Réunion — read differently, the deputy being "
               f"elected there and sitting on boards there."),
    }[lang]
    legend = [(p["series"][0], {"fr": "Circonscription",
                                "en": "Constituency"}[lang]),
              (p["series"][2], {"fr": "Territoire", "en": "Territory"}[lang])]
    table = (
        [{"fr": "Circonscription", "en": "Constituency"}[lang],
         {"fr": "Territoire", "en": "Territory"}[lang],
         {"fr": "Parlementaires", "en": "Parliamentarians"}[lang]],
        [(s, t, n) for s, t, n in pairs[:40]],
    )
    return "".join(body), 500.0, title, legend, caption, table


# --- fig39: direct against proxy -----------------------------------------
def fig_proxy(d, mode, lang):
    p = PALETTE[mode]
    counts = {y: {"self": 0, "relative": 0} for y in SNAPSHOTS}
    for row in d["roster_ties"]:
        y = row.get("snapshot_year")
        if y in counts:
            counts[y][row.get("held_by") or "self"] += 1
    order = [y for y in SNAPSHOTS if sum(counts[y].values())]
    if not order:
        return "", 40.0, "", None, "", None
    hi = max(sum(counts[y].values()) for y in order) or 1
    left, bottom, top = 58.0, 34.0, 20.0
    height = 300.0
    plot_h = height - bottom - top
    col_w = (W - left - 30.0) / max(len(order), 1)
    parts = []
    for j, year in enumerate(order):
        # Thin marks: a five-category axis on a 1340px canvas gives
        # 167px bars at 0.64, which reads as a block rather than a bar.
        x = left + col_w * j + col_w * 0.30
        bw = col_w * 0.40
        y = height - bottom
        for k, kind in enumerate(("self", "relative")):
            n = counts[year][kind]
            if not n:
                continue
            h = plot_h * n / hi
            y -= h
            colour = p["series"][0] if kind == "self" else p["series"][1]
            label = {"self": {"fr": "en propre", "en": "held directly"},
                     "relative": {"fr": "par un proche",
                                  "en": "through a relative"}}[kind][lang]
            parts.append(
                f'<g class="mk"><title>{year} — {esc(label)}: {n}</title>'
                f'<rect x="{x:.1f}" y="{y + (2.0 if k else 0):.1f}" '
                f'width="{bw:.1f}" height="{max(h - (2.0 if k else 0), 1.0):.1f}" '
                f'rx="4" fill="{colour}"/></g>')
            y += 0
        total = sum(counts[year].values())
        parts.append(_axis_text(mode, x + bw / 2, height - bottom + 15, year,
                                "middle", AXIS_FONT))
        parts.append(_axis_text(mode, x + bw / 2,
                                height - bottom - plot_h * total / hi - 6,
                                _fmt(total), "middle", AXIS_FONT))
    parts.append(f'<line x1="{left:.1f}" y1="{height - bottom:.1f}" '
                 f'x2="{W - 30:.1f}" y2="{height - bottom:.1f}" '
                 f'stroke="{p["hairline"]}" stroke-width="1"/>')

    title = {"fr": "fig. 39 — En propre, ou par un proche",
             "en": "fig. 39 — Held directly, or through a relative"}[lang]
    caption = {
        "fr": ("Le titre du groupe de documents dit « intéressés directement "
               "ou par des proches » : le compilateur suit les deux. Les liens "
               "attribués à un parent sont rattachés à ce parent, jamais au "
               "parlementaire, et sont exclus du réseau principal. Ils sont "
               "peu nombreux, mais leur existence est le fait à retenir : la "
               "source distingue le prête-nom, donc le jeu de données aussi."),
        "en": ("The document group's own title says « interested directly or "
               "through relatives »: the compiler tracks both. Ties the roster "
               "attributes to a relative are keyed to that relative, never to "
               "the parliamentarian, and are excluded from the main network. "
               "They are few, but their existence is the point: the source "
               "distinguishes the proxy holding, so the dataset does too."),
    }[lang]
    legend = [(p["series"][0], {"fr": "en propre",
                                "en": "held directly"}[lang]),
              (p["series"][1], {"fr": "par un proche",
                                "en": "through a relative"}[lang])]
    table = (
        [{"fr": "Année", "en": "Year"}[lang],
         {"fr": "En propre", "en": "Direct"}[lang],
         {"fr": "Par un proche", "en": "Through a relative"}[lang]],
        [(y, counts[y]["self"], counts[y]["relative"]) for y in order],
    )
    return "".join(parts), height, title, legend, caption, table


FIGURES = [
    ("fig34_mandate_terms", fig_terms),
    ("fig35_roster_presence", fig_presence),
    ("fig36_legislator_interlock", fig_interlock),
    ("fig37_parliamentary_boards", fig_firms),
    ("fig38_seat_territory", fig_seat_territory),
    ("fig39_direct_or_proxy", fig_proxy),
]


def render_page(d, lang: str) -> str:
    title = {"fr": "Les élites parlementaires et les conseils coloniaux",
             "en": "Parliamentary elites and the colonial boards"}[lang]
    lede = {
        "fr": ("Le compilateur a réuni cinq annuaires pour établir un fait : "
               "des parlementaires siégeaient aux conseils des sociétés "
               "coloniales. Ces six figures posent la question suivante — "
               "de quelle continuité la source témoigne, celle d'une carrière, "
               "celle d'une présence, ou celle de l'accès d'une firme."),
        "en": ("The compiler assembled five directories to establish one "
               "fact: parliamentarians sat on the boards of colonial "
               "companies. These six figures ask the next question — which "
               "continuity the source actually attests: a career's, a "
               "presence's, or a firm's access."),
    }[lang]
    toggle = {"fr": "Basculer le thème", "en": "Toggle theme"}[lang]
    out = [
        f'<!doctype html><html lang="{lang}"><meta charset="utf-8">',
        f"<title>{esc(title)}</title>",
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<style>{PAGE_CSS}</style>",
        f'<h1>{esc(title)}</h1><p class="lede">{esc(lede)}</p>',
        f'<button onclick="document.documentElement.dataset.theme='
        f'document.documentElement.dataset.theme===\'dark\'?\'light\':\'dark\'">'
        f'{esc(toggle)}</button>',
    ]
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
        with open(os.path.join(out_dir, f"{name}.svg"), "w",
                  encoding="utf-8") as fh:
            fh.write(svg)
        written += 1
    with open(os.path.join(out_dir, "legislature.html"), "w",
              encoding="utf-8") as fh:
        fh.write(render_page(d, args.lang))
    print(f"wrote {written} legislative figures + legislature.html to "
          f"{os.path.relpath(out_dir, os.path.dirname(FIG_DIR))}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
