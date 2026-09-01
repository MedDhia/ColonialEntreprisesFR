"""Stage 25 - the two figures behind "composition, not centrality".

    python3 src/make_paris_figures.py
    python3 src/make_paris_figures.py --lang en

    figures/fig59_paris_composition.svg
    figures/fig60_paris_entry_exit.svg
    figures/paris.html

Stage 24 measures why Paris's share of the network falls. These draw the two
claims it rests on, and each is a two-panel figure because each compares
quantities with different denominators — which is what a second y-axis would
hide.

- **fig59** — the falling shares beside the flat ratio. Left: Paris's share of
  the active firms and of the ties, falling together. Right: `degree_ratio`,
  the mean degree of a Paris firm over the mean degree of every other placed
  firm, which never leaves [1.16, 1.39]. The left panel is the phenomenon; the
  right panel is why it is not a loss of centrality.
- **fig60** — entry against exit, then what entry means. Left: for each
  transition, the Paris share of the standing stock, of the firms that leave,
  and of the firms that arrive. Right: the share of arrivals actually founded
  in the period they arrive in, cut by stratum so the founding-year field's
  own bias is visible rather than assumed away.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import draw  # noqa: E402
from common import ensure_dir  # noqa: E402
from labels import LANGS  # noqa: E402
from make_descriptive_figures import PAGE_CSS, PERIOD_LABEL, _axis_text, _table_html  # noqa: E402
from make_figures import FIG_DIR, PALETTE, esc, svg_document  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")

W = 1340.0
GAP = 84.0
LEFT, RIGHT = 58.0, 18.0
TOP, PLOT_H = 48.0, 250.0

PERIOD_FR = {"pre_1914": "avant 1914", "1914_1929": "1914–1929",
             "1930_1944": "1930–1944", "1945_1962": "1945–1962",
             "post_1962": "après 1962"}
STRATUM_LABEL = {
    "fr": {"all": "toutes", "metropole": "métropole", "empire": "empire"},
    "en": {"all": "all firms", "metropole": "metropole", "empire": "empire"},
}
# Short enough to sit under a 22px bar without colliding with its neighbour.
STRATUM_SHORT = {
    "fr": {"all": "tout", "metropole": "métr.", "empire": "emp."},
    "en": {"all": "all", "metropole": "metro", "empire": "emp."},
}


def load(name):
    path = os.path.join(PROC, name)
    if not os.path.exists(path):
        raise SystemExit("run: python3 src/decompose_paris.py")
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def plabel(period, lang):
    return PERIOD_LABEL[period] if lang == "en" else PERIOD_FR[period]


def gather():
    return {"periods": load("paris_decomposition.csv"),
            "moves": load("paris_entry_exit.csv")}


def _panel_frame(body, mode, panel, n, lang, ticks, top_label, labels,
                 label_dy=18.0):
    """Gridlines, y ticks and x labels for one of two side-by-side panels."""
    p = PALETTE[mode]
    pw = (W - GAP) / 2
    x0 = panel * (pw + GAP) + LEFT
    x1 = panel * (pw + GAP) + pw - RIGHT
    for frac, text in ticks:
        y = TOP + PLOT_H * (1 - frac)
        body.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" '
                    f'stroke="{p["hairline"]}" stroke-width="0.8"/>')
        body.append(_axis_text(mode, x0 - 8, y + 3.6, text, "end", font=10.5))
    for i, lab in enumerate(labels):
        x = x0 + (x1 - x0) * ((i + 0.5) / n)
        body.append(_axis_text(mode, x, TOP + PLOT_H + label_dy, lab, "middle",
                               font=10.5))
    body.append(_axis_text(mode, x0, 26, top_label, "start", font=12.5))
    return x0, x1


def _x_of(panel, i, n):
    pw = (W - GAP) / 2
    x0 = panel * (pw + GAP) + LEFT
    span = pw - LEFT - RIGHT
    return x0 + span * ((i + 0.5) / n)


def _line(body, mode, panel, values, colour, n, ymax=1.0, label_ends=True,
          fmt="{:.0%}"):
    pts = [(_x_of(panel, i, n), TOP + PLOT_H * (1 - v / ymax))
           for i, v in enumerate(values)]
    body.append('<path d="M' + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
                + f'" fill="none" stroke="{colour}" stroke-width="2" '
                f'stroke-linejoin="round"/>')
    p = PALETTE[mode]
    for x, y in pts:
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.2" fill="{colour}" '
                    f'stroke="{p["surface"]}" stroke-width="2"/>')
    if label_ends:
        for idx in (0, len(pts) - 1):
            body.append(draw.halo_text(mode, pts[idx][0], pts[idx][1] - 12,
                                       fmt.format(values[idx]), "middle", font=10.5))


# --- fig59: composition, not centrality -----------------------------------
def fig_composition(d, mode, lang):
    p = PALETTE[mode]
    rows = d["periods"]
    n = len(rows)
    labels = [plabel(r["period"], lang) for r in rows]
    body = []

    _panel_frame(body, mode, 0, n, lang,
                 [(f, f"{f * 100:.0f}%") for f in (0, .25, .5, .75, 1.0)],
                 {"fr": "Part parisienne, qui baisse",
                  "en": "Paris's share, which falls"}[lang], labels)
    _line(body, mode, 0, [float(r["share_paris_edges"]) for r in rows],
          p["series"][0], n)
    _line(body, mode, 0, [float(r["share_paris_firms"]) for r in rows],
          p["series"][2], n)

    # The right panel is a ratio, not a share, so it gets its own axis and its
    # own panel. A second y-axis on the left panel would invite the reader to
    # see one line crossing another and call it a finding.
    ymax = 2.0
    _panel_frame(body, mode, 1, n,
                 lang, [(v / ymax, f"{v:.1f}×") for v in (0.5, 1.0, 1.5, 2.0)],
                 {"fr": "Connectivité relative de Paris, qui ne baisse pas",
                  "en": "Paris's relative connectivity, which does not"}[lang],
                 labels)
    x0, x1 = _x_of(1, 0, n) - 20, _x_of(1, n - 1, n) + 20
    y1 = TOP + PLOT_H * (1 - 1.0 / ymax)
    body.append(f'<line x1="{x0:.1f}" y1="{y1:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
                f'stroke="{p["other"]}" stroke-width="1.4" stroke-dasharray="5 4"/>')
    body.append(_axis_text(mode, x1 + 4, y1 + 3.6,
                           {"fr": "parité", "en": "parity"}[lang], "start", font=10))
    _line(body, mode, 1, [float(r["degree_ratio"]) for r in rows],
          p["series"][1], n, ymax=ymax, fmt="{:.2f}×")

    ratios = [float(r["degree_ratio"]) for r in rows]
    first, last = rows[0], rows[-1]
    title = {"fr": "Paris recule par composition, pas par perte de centralité",
             "en": "Paris recedes by composition, not by losing centrality"}[lang]
    caption = {
        "fr": (f"À gauche, la part des liens traçables qui touchent Paris tombe de "
               f"{100 * float(first['share_paris_edges']):.1f} % à "
               f"{100 * float(last['share_paris_edges']):.1f} %, et la part des "
               f"entreprises actives situées à Paris de "
               f"{100 * float(first['share_paris_firms']):.1f} % à "
               f"{100 * float(last['share_paris_firms']):.1f} % : les deux courbes "
               f"descendent ensemble. À droite, le degré moyen d'une entreprise "
               f"parisienne rapporté à celui des autres entreprises situées reste "
               f"entre {min(ratios):.2f}× et {max(ratios):.2f}×, sans tendance. Une "
               f"entreprise parisienne des années 1960 est aussi bien connectée, "
               f"relativement, qu'une entreprise parisienne des années 1890. Paris "
               f"n'a pas cessé d'être un moyeu ; le fonds a cessé d'être parisien."),
        "en": (f"Left: the share of drawable ties touching Paris falls from "
               f"{100 * float(first['share_paris_edges']):.1f}% to "
               f"{100 * float(last['share_paris_edges']):.1f}%, and Paris's share of "
               f"the active firms from "
               f"{100 * float(first['share_paris_firms']):.1f}% to "
               f"{100 * float(last['share_paris_firms']):.1f}% — the two fall "
               f"together. Right: the mean degree of a Paris firm over the mean "
               f"degree of every other placed firm stays between {min(ratios):.2f}× "
               f"and {max(ratios):.2f}×, with no trend. A Paris firm in the 1960s is "
               f"as disproportionately connected as a Paris firm in the 1890s. Paris "
               f"did not stop being a hub; the record stopped being Parisian."),
    }[lang]
    legend = [(p["series"][0], {"fr": "part des liens", "en": "share of ties"}[lang]),
              (p["series"][2], {"fr": "part des entreprises",
                                "en": "share of firms"}[lang]),
              (p["series"][1], {"fr": "degré relatif (échelle de droite)",
                                "en": "relative degree (right panel)"}[lang])]
    head = {"fr": ["Période", "Entreprises", "Paris", "% entreprises", "% liens",
                   "Degré Paris", "Degré autres", "Rapport"],
            "en": ["Period", "Firms", "Paris", "% firms", "% ties",
                   "Degree Paris", "Degree other", "Ratio"]}[lang]
    table = (head, [[plabel(r["period"], lang), f"{int(r['n_firms']):,}",
                     f"{int(r['n_paris_firms']):,}",
                     f"{100 * float(r['share_paris_firms']):.1f}%",
                     f"{100 * float(r['share_paris_edges']):.1f}%",
                     r["mean_degree_paris"], r["mean_degree_other"],
                     f"{float(r['degree_ratio']):.2f}×"] for r in rows])
    return "".join(body), TOP + PLOT_H + 40, title, legend, caption, table


# --- fig60: entry, exit, and what entry means -----------------------------
def fig_entry_exit(d, mode, lang):
    p = PALETTE[mode]
    rows = [r for r in d["moves"] if r["stratum"] == "all"]
    n = len(rows)
    short = [plabel(r["to_period"], lang) for r in rows]
    body = []

    ymax = 0.4
    _panel_frame(body, mode, 0, n, lang,
                 [(f / ymax, f"{f * 100:.0f}%") for f in (0, .1, .2, .3, .4)],
                 {"fr": "Part parisienne : stock, sorties, entrées",
                  "en": "Paris share: standing stock, leavers, arrivals"}[lang], short)
    for key, colour in (("share_paris_base", p["other"]),
                        ("share_paris_exit", p["series"][1]),
                        ("share_paris_enter", p["series"][0])):
        _line(body, mode, 0, [min(float(r[key]), ymax) for r in rows], colour, n,
              ymax=ymax, label_ends=False)

    # Right: the share of arrivals founded in the period they arrive in, by
    # stratum. Grouped bars, because each stratum is its own denominator.
    _panel_frame(body, mode, 1, n, lang,
                 [(f, f"{f * 100:.0f}%") for f in (0, .25, .5, .75, 1.0)],
                 {"fr": "Part des entrants fondés dans la période",
                  "en": "Share of arrivals founded in that period"}[lang], short,
                 label_dy=34.0)
    # One hue for all three bars, with the stratum named under each. The left
    # panel already spends three colours on stock/leavers/arrivals, and a hue
    # that means "arrivals" on the left and "all firms" on the right would be
    # the same ink carrying two meanings inside one figure.
    strata = ["all", "metropole", "empire"]
    band = ((W - GAP) / 2 - LEFT - RIGHT) / n
    bw = min(22.0, band / (len(strata) + 1.4))
    by_key = {(r["from_period"], r["stratum"]): r for r in d["moves"]}
    for i, r in enumerate(rows):
        cx = _x_of(1, i, n)
        for j, st in enumerate(strata):
            row = by_key.get((r["from_period"], st))
            if not row or not row["share_founded_in_period"]:
                continue
            v = float(row["share_founded_in_period"])
            x = cx + (j - (len(strata) - 1) / 2) * (bw + 2) - bw / 2
            y = TOP + PLOT_H * (1 - v)
            body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                        f'height="{TOP + PLOT_H - y:.1f}" rx="3" '
                        f'fill="{p["series"][2]}"/>')
            body.append(_axis_text(mode, x + bw / 2, TOP + PLOT_H + 18,
                                   STRATUM_SHORT[lang][st], "middle", font=8.5))
            if st == "all":
                body.append(draw.halo_text(mode, x + bw / 2, y - 6,
                                           f"{v * 100:.0f}%", "middle", font=10.5))

    first, last = rows[0], rows[-1]
    title = {"fr": "Ce sont les entrées qui déplacent le réseau — et elles changent de sens",
             "en": "Arrivals move the network — and what an arrival is changes"}[lang]
    caption = {
        "fr": (f"À gauche : à chaque transition, les entreprises qui arrivent sont "
               f"bien moins parisiennes que le stock qu'elles rejoignent "
               f"({100 * float(first['share_paris_enter']):.1f} % contre "
               f"{100 * float(first['share_paris_base']):.1f} % d'abord, "
               f"{100 * float(last['share_paris_enter']):.1f} % contre "
               f"{100 * float(last['share_paris_base']):.1f} % à la fin), tandis que "
               f"celles qui sortent ressemblent au stock. Rien ne chasse Paris ; "
               f"quelque chose de non parisien arrive. Une entreprise n'a qu'un seul "
               f"point d'ancrage pour toute la période couverte, donc la composition "
               f"ne peut changer que par entrée et sortie : c'est une contrainte du "
               f"jeu de données, pas un résultat. À droite : la part des entrants "
               f"réellement fondés dans la période où ils apparaissent s'effondre de "
               f"{100 * float(first['share_founded_in_period']):.0f} % à "
               f"{100 * float(last['share_founded_in_period']):.0f} %. Au début ce "
               f"sont de vraies créations ; à la fin ce sont de vieilles entreprises "
               f"dont le compilateur parle enfin. Les trois barres montrent que la "
               f"chute tient dans chaque strate, donc qu'elle n'est pas un artefact "
               f"du champ « année de fondation », mieux rempli en métropole."),
        "en": (f"Left: at every transition the arriving firms are far less Parisian "
               f"than the stock they join — "
               f"{100 * float(first['share_paris_enter']):.1f}% against "
               f"{100 * float(first['share_paris_base']):.1f}% at the start, "
               f"{100 * float(last['share_paris_enter']):.1f}% against "
               f"{100 * float(last['share_paris_base']):.1f}% at the end — while the "
               f"leavers look like the stock. Nothing pushes Paris out; something "
               f"non-Parisian arrives. A firm carries one anchor for the whole period "
               f"covered, so composition can change only by entry and exit: that is a "
               f"constraint of the dataset, not a finding. Right: the share of "
               f"arrivals actually founded in the period they arrive in collapses "
               f"from {100 * float(first['share_founded_in_period']):.0f}% to "
               f"{100 * float(last['share_founded_in_period']):.0f}%. Early on these "
               f"are real new firms; at the end they are old firms the compiler is "
               f"only now writing about. The three bars show the collapse holds "
               f"inside each stratum, so it is not an artefact of the founding-year "
               f"field being better recorded in the metropole."),
    }[lang]
    legend = [(p["other"], {"fr": "stock en place", "en": "standing stock"}[lang]),
              (p["series"][1], {"fr": "sorties", "en": "leavers"}[lang]),
              (p["series"][0], {"fr": "entrées", "en": "arrivals"}[lang]),
              (p["series"][2], {"fr": "fondés dans la période (panneau droit)",
                                "en": "founded in-period (right panel)"}[lang])]
    head = {"fr": ["Transition", "Strate", "Stock", "% Paris stock", "Sorties",
                   "% Paris sorties", "Entrées", "% Paris entrées",
                   "Datés", "Fondés dans la période"],
            "en": ["Transition", "Stratum", "Stock", "% Paris stock", "Leavers",
                   "% Paris leavers", "Arrivals", "% Paris arrivals",
                   "Dated", "Founded in-period"]}[lang]
    table = (head, [[
        f"{plabel(r['from_period'], lang)} → {plabel(r['to_period'], lang)}",
        STRATUM_LABEL[lang][r["stratum"]],
        f"{int(r['n_base']):,}", f"{100 * float(r['share_paris_base']):.1f}%",
        f"{int(r['n_exit']):,}", f"{100 * float(r['share_paris_exit']):.1f}%",
        f"{int(r['n_enter']):,}", f"{100 * float(r['share_paris_enter']):.1f}%",
        f"{int(r['n_enter_dated']):,}",
        f"{int(r['n_enter_founded_in_period']):,}"
        f" ({100 * float(r['share_founded_in_period'] or 0):.0f}%)",
    ] for r in d["moves"]])
    return "".join(body), TOP + PLOT_H + 56, title, legend, caption, table


FIGURES = [("fig59_paris_composition", fig_composition),
           ("fig60_paris_entry_exit", fig_entry_exit)]


def render_page(d, lang):
    title = {"fr": "Pourquoi Paris recule", "en": "Why Paris recedes"}[lang]
    lede = {
        "fr": ("La part parisienne du réseau baisse à chaque période. Ce n'est pas "
               "une perte de centralité — le degré relatif d'une entreprise "
               "parisienne ne bouge pas — mais un effet de composition, porté par "
               "les entrées ; et ce qu'« entrer » veut dire change en cours de route."),
        "en": ("Paris's share of the network falls in every period. It is not a loss "
               "of centrality — a Paris firm's relative degree does not move — but a "
               "compositional effect carried by arrivals; and what an arrival is "
               "changes along the way."),
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
        svg = svg_document(body, W, height, "vars", ftitle, legend=legend, caption="")
        out.append(f'<figure id="{name}"><h2 style="font-size:16px;margin:0 0 2px">'
                   f'{esc(ftitle)}</h2><figcaption>{esc(caption)}</figcaption>'
                   f'{svg}{_table_html(table, lang)}</figure>')
    out.append("</html>")
    return "".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=LANGS, default="fr")
    args = ap.parse_args()
    out_dir = FIG_DIR if args.lang == "fr" else os.path.join(FIG_DIR, args.lang)
    ensure_dir(out_dir)

    d = gather()
    for name, fn in FIGURES:
        body, height, title, legend, caption, _ = fn(d, "light", args.lang)
        with open(os.path.join(out_dir, f"{name}.svg"), "w", encoding="utf-8") as fh:
            fh.write(svg_document(body, W, height, "light", title,
                                  legend=legend, caption=caption))
    with open(os.path.join(out_dir, "paris.html"), "w", encoding="utf-8") as fh:
        fh.write(render_page(d, args.lang))
    print(f"wrote {len(FIGURES)} figures + paris.html to "
          f"{os.path.relpath(out_dir, os.path.dirname(FIG_DIR))}", file=sys.stderr)


if __name__ == "__main__":
    main()
