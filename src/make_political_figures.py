"""Stage 17 - the political-connection coding, in five figures.

    python3 src/make_political_figures.py            # -> figures/fig40..44
    python3 src/make_political_figures.py --lang en

The coding is in `company_political.csv` and argued in
`data/reference/political_connection_rules.md`. These figures are built to make
the coding's *limits* as visible as its findings, because a single "35% of firms
were politically connected" is the number a reader will take away and it is the
number that needs the most qualification.

- **fig40, the tiers.** How the 6,454 firms with a board distribute across the
  five tiers. A ranked magnitude over an ordered category, so columns, with the
  indirect-only count set beside tier 0 rather than inside it.
- **fig41, sitting against former.** The revolving door, by tier. Two series,
  never summed, because `former` is read from the source's own `ancien` and is
  a floor while `sitting` is a ceiling.
- **fig42, by territory.** Share of firms connected, per territory, with the
  firm count beside it — a share over 12 firms and a share over 800 are not the
  same measurement and the figure has to say so.
- **fig43, the connected boards.** Firms ranked by how many connected directors
  sit on them, with the board size behind it, so a big count on a big board
  reads differently from a big count on a small one.
- **fig44, concurrency.** Of the director-firm pairs where both the tie year and
  the office span are known, how many actually overlap. This is the honest
  denominator figure: it shows how small the well-evidenced subset is.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ensure_dir  # noqa: E402
from labels import LANGS, localise  # noqa: E402
from make_descriptive_figures import (PAGE_CSS, _axis_text, _fmt,  # noqa: E402
                                      _table_html, hbars)
from make_figures import (PALETTE, FIG_DIR, esc, svg_document,  # noqa: E402
                          trim_to_width)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")

W = 1340.0
AXIS_FONT = 10.5
TIERS = [4, 3, 2, 1, 0]
TOP_FIRMS = 18
MIN_TERR_FIRMS = 25     # below this a share is noise, and the figure says so
TOP_TERR = 14


def load(name):
    path = os.path.join(PROC, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def gather():
    return {"firms": load("company_political.csv"),
            "terr": load("political_connections_by_territory.csv")}


TIER_LABEL = {
    4: {"fr": "Exécutif", "en": "Executive"},
    3: {"fr": "Législatif", "en": "Legislature"},
    2: {"fr": "Administration", "en": "Administration"},
    1: {"fr": "Local ou par un proche", "en": "Local or proxy"},
    0: {"fr": "Aucune", "en": "None"},
}


def _tier(t, lang):
    return TIER_LABEL[t][lang]


def columns_simple(rows, width, height, mode, colour_of=None, value_fmt=_fmt,
                   note=""):
    """Vertical columns over an ordered category. Rows are (label, value, tip)."""
    p = PALETTE[mode]
    left, bottom, top = 46.0, 34.0, 26.0
    plot_h = height - bottom - top
    hi = max((v for _, v, _ in rows), default=1) or 1
    col_w = (width - left - 24.0) / max(len(rows), 1)
    parts = []
    if note:
        parts.append(_axis_text(mode, left, 12.0, note, font=AXIS_FONT,
                                muted=True))
    for j, (label, value, tip) in enumerate(rows):
        x = left + col_w * j + col_w * 0.30
        bw = col_w * 0.40
        h = plot_h * value / hi
        y = height - bottom - h
        parts.append(
            f'<g class="mk"><title>{esc(tip)}</title>'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
            f'height="{max(h, 1.0):.1f}" rx="4" '
            f'fill="{(colour_of(j) if colour_of else p["series"][0])}"/></g>')
        parts.append(_axis_text(mode, x + bw / 2, y - 6, value_fmt(value),
                                "middle", AXIS_FONT))
        parts.append(_axis_text(
            mode, x + bw / 2, height - bottom + 15,
            trim_to_width(label, AXIS_FONT, col_w - 4), "middle", AXIS_FONT))
    parts.append(f'<line x1="{left:.1f}" y1="{height - bottom:.1f}" '
                 f'x2="{width - 24:.1f}" y2="{height - bottom:.1f}" '
                 f'stroke="{p["hairline"]}" stroke-width="1"/>')
    return "".join(parts)


# --- fig40: the tiers -----------------------------------------------------
def fig_tiers(d, mode, lang):
    p = PALETTE[mode]
    firms = d["firms"]
    if not firms:
        return "", 40.0, "", None, "", None
    counts = collections.Counter(int(r["connection_tier"]) for r in firms)
    total = len(firms)
    # Tier 0 is not plotted. It is the absence of the thing being measured,
    # not a fifth degree of it, and at 4,208 against 887 it flattened the four
    # bars that carry the finding into unreadable stubs. Its size is stated in
    # the note above the axis and again in the caption, so nothing is hidden.
    drawn = [t for t in TIERS if t > 0]
    rows = [(_tier(t, lang), counts[t],
             f"{_tier(t, lang)}: {counts[t]:,} / {total:,} "
             f"({counts[t] / total:.1%})") for t in drawn]
    indirect = sum(1 for r in firms if r["indirect_only"] == "1")
    conn = total - counts[0]
    note = {
        "fr": (f"Non représenté : {counts[0]:,} sociétés "
               f"({counts[0] / total:.0%}) sans connexion attestée, dont "
               f"{indirect:,} partagent un administrateur avec une société "
               f"connectée."),
        "en": (f"Not plotted: {counts[0]:,} firms ({counts[0] / total:.0%}) "
               f"with no connection attested, of which {indirect:,} share a "
               f"director with a connected firm."),
    }[lang]
    body = columns_simple(
        rows, W, 300.0, mode, note=note,
        colour_of=lambda j: (p["series"][0] if drawn[j] >= 3
                             else p["series"][2]))
    title = {"fr": "fig. 40 — La connexion politique, par degré",
             "en": "fig. 40 — Political connection, by tier"}[lang]
    caption = {
        "fr": (f"Les {total:,} sociétés ayant au moins un siège de conseil "
               f"observé. {conn:,} ({conn / total:.0%}) ont au moins un "
               f"administrateur attesté dans une fonction publique. Sur les "
               f"{counts[0]:,} sans connexion propre, {indirect:,} partagent "
               f"un administrateur avec une société connectée : la connexion "
               f"indirecte n'est pas comptée dans le degré, et c'est délibéré "
               f"— être à un lien du conseil d'un ministre n'est pas la même "
               f"chose que d'avoir ce ministre au sien."),
        "en": (f"The {total:,} companies with at least one observed board "
               f"seat. {conn:,} ({conn / total:.0%}) have a director attested "
               f"in public office. Of the {counts[0]:,} with no connection of "
               f"their own, {indirect:,} share a director with a connected "
               f"firm: indirect connection is deliberately not counted in the "
               f"tier — one interlock from a minister's board is not the same "
               f"thing as having the minister on yours."),
    }[lang]
    table = ([{"fr": "Degré", "en": "Tier"}[lang],
              {"fr": "Sociétés", "en": "Companies"}[lang],
              {"fr": "Part", "en": "Share"}[lang]],
             [(_tier(t, lang), counts[t], f"{counts[t] / total:.1%}")
              for t in TIERS])   # the table keeps tier 0
    return body, 300.0, title, None, caption, table


# --- fig41: sitting against former ---------------------------------------
def fig_revolving(d, mode, lang):
    p = PALETTE[mode]
    firms = [r for r in d["firms"] if int(r["connection_tier"]) > 0]
    if not firms:
        return "", 40.0, "", None, "", None
    by_tier = collections.defaultdict(lambda: [0, 0])
    for r in firms:
        t = int(r["connection_tier"])
        if r["has_sitting"] == "1":
            by_tier[t][0] += 1
        if r["has_former"] == "1":
            by_tier[t][1] += 1
    order = [t for t in TIERS if t > 0]
    left, bottom, top, height = 46.0, 34.0, 26.0, 300.0
    plot_h = height - bottom - top
    hi = max(max(v) for v in by_tier.values()) or 1
    col_w = (W - left - 24.0) / max(len(order), 1)
    parts = []
    for j, t in enumerate(order):
        sit, form = by_tier[t]
        for k, (n, colour) in enumerate(((sit, p["series"][0]),
                                         (form, p["series"][1]))):
            # Two adjacent bars, never stacked: the two are not parts of a
            # whole and a firm can be counted in both.
            x = left + col_w * j + col_w * (0.22 + 0.26 * k)
            bw = col_w * 0.22
            h = plot_h * n / hi
            y = height - bottom - h
            lab = ({"fr": "en fonction", "en": "sitting"} if k == 0
                   else {"fr": "ancien", "en": "former"})[lang]
            parts.append(
                f'<g class="mk"><title>{esc(_tier(t, lang))} — {esc(lab)}: '
                f'{n:,}</title><rect x="{x:.1f}" y="{y:.1f}" '
                f'width="{bw:.1f}" height="{max(h, 1.0):.1f}" rx="4" '
                f'fill="{colour}"/></g>')
            parts.append(_axis_text(mode, x + bw / 2, y - 6, _fmt(n),
                                    "middle", AXIS_FONT))
        parts.append(_axis_text(mode, left + col_w * (j + 0.5),
                                height - bottom + 15, _tier(t, lang),
                                "middle", AXIS_FONT))
    parts.append(f'<line x1="{left:.1f}" y1="{height - bottom:.1f}" '
                 f'x2="{W - 24:.1f}" y2="{height - bottom:.1f}" '
                 f'stroke="{p["hairline"]}" stroke-width="1"/>')
    title = {"fr": "fig. 41 — En fonction, ou ancien",
             "en": "fig. 41 — Sitting, or former"}[lang]
    caption = {
        "fr": ("Un administrateur en fonction est un conflit d'intérêts ; un "
               "ancien gouverneur général est une porte tournante. Les deux "
               "ne sont jamais additionnés et une société peut compter dans "
               "les deux. « Ancien » est lu dans les mots de la source — "
               "« ancien », « honoraire », « en retraite » — que le "
               "compilateur omet bien plus souvent qu'il n'omet la fonction "
               "elle-même : lire les barres oranges comme un plancher et les "
               "bleues comme un plafond."),
        "en": ("A sitting office-holder on a board is a conflict of interest; "
               "a retired governor-general is a revolving door. The two are "
               "never summed and a firm can count in both. `former` is read "
               "from the source's own words — *ancien*, *honoraire*, *en "
               "retraite* — which the compiler omits far more often than he "
               "omits the office itself: read the orange bars as a floor and "
               "the blue as a ceiling."),
    }[lang]
    legend = [(p["series"][0], {"fr": "en fonction", "en": "sitting"}[lang]),
              (p["series"][1], {"fr": "ancien", "en": "former"}[lang])]
    table = ([{"fr": "Degré", "en": "Tier"}[lang],
              {"fr": "En fonction", "en": "Sitting"}[lang],
              {"fr": "Ancien", "en": "Former"}[lang]],
             [(_tier(t, lang), by_tier[t][0], by_tier[t][1]) for t in order])
    return "".join(parts), height, title, legend, caption, table


# --- fig42: by territory -------------------------------------------------
def fig_territory(d, mode, lang):
    rows = [r for r in d["terr"]
            if int(r["n_firms"]) >= MIN_TERR_FIRMS
            and r["territory"] != "(unlabelled)"]
    if not rows:
        return "", 40.0, "", None, "", None
    rows.sort(key=lambda r: -float(r["share_connected"]))
    rows = rows[:TOP_TERR]
    bars = []
    for r in rows:
        share = float(r["share_connected"])
        label = f"{localise(r['territory'], lang)}  ({int(r['n_firms']):,})"
        bars.append((label, share * 100,
                     f"{localise(r['territory'], lang)}: "
                     f"{int(r['n_connected']):,} / {int(r['n_firms']):,}"))
    body, height = hbars(bars, W, mode, label_w=320.0, row_h=26.0,
                         value_fmt=lambda v: f"{v:.0f}%")
    title = {"fr": "fig. 42 — Part des sociétés connectées, par territoire",
             "en": "fig. 42 — Share of firms connected, by territory"}[lang]
    caption = {
        "fr": (f"Territoires comptant au moins {MIN_TERR_FIRMS} sociétés avec "
               f"un conseil ; le nombre entre parenthèses est ce dénominateur, "
               f"parce qu'une part sur 30 sociétés et une part sur 800 ne sont "
               f"pas la même mesure. Ces écarts reflètent d'abord la couverture "
               f"documentaire : un territoire que le compilateur a lu de près "
               f"paraîtra plus connecté, pour des raisons qui ne tiennent pas "
               f"à ses firmes. Ne pas lire comme un taux."),
        "en": (f"Territories with at least {MIN_TERR_FIRMS} firms holding a "
               f"board; the number in brackets is that denominator, because a "
               f"share over 30 firms and a share over 800 are not the same "
               f"measurement. These gaps track documentary coverage first: a "
               f"territory the compiler read closely looks more connected, for "
               f"reasons that have nothing to do with its firms. Not a rate."),
    }[lang]
    table = ([{"fr": "Territoire", "en": "Territory"}[lang],
              {"fr": "Sociétés", "en": "Firms"}[lang],
              {"fr": "Connectées", "en": "Connected"}[lang],
              {"fr": "Part", "en": "Share"}[lang]],
             [(localise(r["territory"], lang), r["n_firms"], r["n_connected"],
               f"{float(r['share_connected']):.1%}") for r in rows])
    return body, height, title, None, caption, table


# --- fig43: the connected boards -----------------------------------------
def fig_boards(d, mode, lang):
    p = PALETTE[mode]
    firms = sorted((r for r in d["firms"] if int(r["n_connected"]) > 0),
                   key=lambda r: (-int(r["n_connected"]), r["company_id"]))
    firms = firms[:TOP_FIRMS]
    if not firms:
        return "", 40.0, "", None, "", None
    label_w, right, row_h, top = 380.0, 120.0, 26.0, 22.0
    # 40px of slack, not 14: `trim_to_width` will not cut below its
    # 10-character floor, so a long firm name needs the budget to be the
    # constraint rather than the floor.
    label_avail = label_w - 40
    plot_w = W - label_w - right
    hi = max(int(r["n_directors"]) for r in firms) or 1
    height = top + len(firms) * row_h + 12.0
    parts = []
    for i, r in enumerate(firms):
        y = top + i * row_h
        cy = y + row_h / 2
        n_all, n_conn = int(r["n_directors"]), int(r["n_connected"])
        w_all = plot_w * n_all / hi
        w_conn = plot_w * n_conn / hi
        tip = (f"{r['name']}: {n_conn} / {n_all} "
               + ("administrateurs connectés" if lang == "fr"
                  else "connected directors")
               + f" ({n_conn / n_all:.0%})")
        parts.append(
            f'<g class="mk"><title>{esc(tip)}</title>'
            f'{_axis_text(mode, label_w - 10, cy + 3.8, trim_to_width(r["name"], AXIS_FONT, label_avail), "end")}'
            # The board behind, the connected share in front: a count of 12 on
            # a board of 63 reads differently from 12 on a board of 20.
            f'<rect x="{label_w:.1f}" y="{y + 5:.1f}" width="{max(w_all, 2.0):.1f}" '
            f'height="{row_h - 12:.1f}" rx="4" fill="{p["other"]}" '
            f'fill-opacity="0.42"/>'
            f'<rect x="{label_w:.1f}" y="{y + 5:.1f}" width="{max(w_conn, 2.0):.1f}" '
            f'height="{row_h - 12:.1f}" rx="4" fill="{p["series"][0]}"/>'
            f'{_axis_text(mode, label_w + max(w_all, 2.0) + 8, cy + 3.8, f"{n_conn} / {n_all}", "start", AXIS_FONT, muted=True)}'
            f'</g>')
    title = {"fr": "fig. 43 — Les conseils les plus connectés",
             "en": "fig. 43 — The most connected boards"}[lang]
    caption = {
        "fr": ("Nombre d'administrateurs attestés dans une fonction publique "
               "(en bleu) sur l'effectif total du conseil observé (en gris), "
               "toutes années confondues. L'effectif total est cumulé sur "
               "toute la période : ce n'est pas la taille du conseil une année "
               "donnée, et la part ne doit pas être lue comme telle."),
        "en": ("Directors attested in public office (blue) against the total "
               "board membership observed (grey), all years pooled. The total "
               "is cumulative over the whole period: it is not the size of the "
               "board in any one year, and the share should not be read as if "
               "it were."),
    }[lang]
    legend = [(p["series"][0], {"fr": "administrateurs connectés",
                               "en": "connected directors"}[lang]),
              (p["other"], {"fr": "conseil observé",
                            "en": "board observed"}[lang])]
    table = ([{"fr": "Société", "en": "Company"}[lang],
              {"fr": "Connectés", "en": "Connected"}[lang],
              {"fr": "Conseil", "en": "Board"}[lang],
              {"fr": "Degré", "en": "Tier"}[lang]],
             [(r["name"], r["n_connected"], r["n_directors"],
               _tier(int(r["connection_tier"]), lang)) for r in firms])
    return "".join(parts), height, title, legend, caption, table


# --- fig44: concurrency --------------------------------------------------
def fig_concurrency(d, mode, lang):
    p = PALETTE[mode]
    firms = d["firms"]
    if not firms:
        return "", 40.0, "", None, "", None
    pairs = sum(int(r["n_connected"]) for r in firms)
    testable = sum(int(r["n_testable"]) for r in firms)
    concurrent = sum(int(r["n_concurrent"]) for r in firms)
    rows = [
        ({"fr": "Paires connectées", "en": "Connected pairs"}[lang], pairs,
         {"fr": "un administrateur connecté, une société",
          "en": "one connected director, one firm"}[lang]),
        ({"fr": "Testables", "en": "Testable"}[lang], testable,
         {"fr": "année du lien et durée du mandat toutes deux connues",
          "en": "tie year and office span both known"}[lang]),
        ({"fr": "Concomitantes", "en": "Concurrent"}[lang], concurrent,
         {"fr": "la fonction couvre une année où le lien est observé",
          "en": "office covers a year the tie was observed"}[lang]),
    ]
    body = columns_simple(
        rows, W, 280.0, mode,
        colour_of=lambda j: (p["other"] if j == 0 else
                             p["series"][2] if j == 1 else p["series"][0]))
    title = {"fr": "fig. 44 — Ce que l'on peut vérifier",
             "en": "fig. 44 — What can actually be tested"}[lang]
    caption = {
        "fr": (f"De {pairs:,} paires administrateur-société connectées, "
               f"{testable:,} ({testable / pairs:.1%}) ont à la fois une année "
               f"de lien et une durée de mandat, et {concurrent:,} de "
               f"celles-là se recouvrent. `n_concurrent` n'est pas une version "
               f"corrigée de `n_connected` : c'est un sous-ensemble bien plus "
               f"petit et bien mieux étayé. À utiliser quand l'affirmation "
               f"porte sur un conflit d'intérêts effectif ; `n_connected` "
               f"quand elle porte sur le recrutement d'une firme dans la "
               f"classe politique, qui n'exige pas la simultanéité."),
        "en": (f"Of {pairs:,} connected director-firm pairs, {testable:,} "
               f"({testable / pairs:.1%}) carry both a tie year and an office "
               f"span, and {concurrent:,} of those overlap. `n_concurrent` is "
               f"not a corrected `n_connected`: it is a much smaller, much "
               f"better-evidenced subset. Use it when the claim is about a "
               f"live conflict of interest; use `n_connected` when the claim "
               f"is about a firm recruiting from the political class, which "
               f"does not require simultaneity."),
    }[lang]
    table = ([{"fr": "Mesure", "en": "Measure"}[lang],
              {"fr": "Paires", "en": "Pairs"}[lang],
              {"fr": "Définition", "en": "Definition"}[lang]],
             [(a, b, c) for a, b, c in rows])
    return body, 280.0, title, None, caption, table


FIGURES = [
    ("fig40_connection_tiers", fig_tiers),
    ("fig41_sitting_or_former", fig_revolving),
    ("fig42_connection_by_territory", fig_territory),
    ("fig43_connected_boards", fig_boards),
    ("fig44_concurrency", fig_concurrency),
]


def render_page(d, lang):
    title = {"fr": "Les sociétés et l'État",
             "en": "The companies and the state"}[lang]
    lede = {
        "fr": ("Une société est codée « connectée » quand l'un de ses "
               "administrateurs est attesté dans une fonction publique. Ces "
               "cinq figures donnent le résultat et, autant que possible, ses "
               "limites : les règles, les fonctions retenues et écartées, et "
               "les quatre choses que ce codage ne peut pas faire sont dans "
               "data/reference/political_connection_rules.md."),
        "en": ("A company is coded connected when one of its directors is "
               "attested holding an office of state. These five figures give "
               "the result and, as far as possible, its limits: the rules, the "
               "offices kept and rejected, and the four things this coding "
               "cannot do are in "
               "data/reference/political_connection_rules.md."),
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
        with open(os.path.join(out_dir, f"{name}.svg"), "w",
                  encoding="utf-8") as fh:
            fh.write(svg)
        written += 1
    with open(os.path.join(out_dir, "political.html"), "w",
              encoding="utf-8") as fh:
        fh.write(render_page(d, args.lang))
    print(f"wrote {written} political figures + political.html to "
          f"{os.path.relpath(out_dir, os.path.dirname(FIG_DIR))}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
