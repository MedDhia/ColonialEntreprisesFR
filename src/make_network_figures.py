"""Stage 12 - the structural figures.

    python3 src/make_network_figures.py            # -> figures/fig18..fig27
    python3 src/make_network_figures.py --lang en  # -> figures/en/

Stage 7 draws the interlock network; stage 11 describes the observations it is
built from. Neither says what *shape* the network has, and the shape is where
the analysis actually starts. A reader who wants to compute anything on this
graph needs to know, before they do, that it is one component and not many,
that its deepest core is a clique one man produces on his own, that half of it
disappears the moment you ask for a second shared director, and that two thirds
of its edges cross a colonial border.

Ten figures, each a measurement rather than a picture of one:

    fig18  degree distribution, log-log        how unequal is connection
    fig19  k-core profile                      where the artefacts hide
    fig20  community backbone                  how the clusters connect
    fig21  giant component vs edge threshold   how much rests on single ties
    fig22  shortest-path distribution          how small the world is
    fig23  community x territory               do clusters follow the empire
    fig24  cross-territory interlocks          how transversal, and when
    fig25  individual reach                    who spans the most territories
    fig26  the innermost core, minus one man   what one name holds up
    fig27  structure by period                 what a period slice is worth

Two of the ten are node-link drawings and eight are charts, which is the
proportion the questions ask for: "is this graph one lump or several" is a
number, and drawing it as a hairball would be answering a measurement with an
illustration. The two that *are* drawn are drawn because their claim is about
adjacency itself — which clusters touch, and what is left of a clique when one
vertex-cover is removed.

Every measurement here is also written to `data/processed/network_measures.csv`
so a reader can quote it without re-deriving it from an SVG.

Reproducibility works exactly as it does in stage 7, and for the same reason:
`louvain_communities` returns a list of *sets*, `core_number` a dict keyed by
node, and `connected_components` a generator of sets. Every one of those
iterates in Python's per-process randomised string-hash order, so each is
sorted into a total order before anything downstream reads it. The path-length
sample draws from a sorted list with an explicit seeded RNG for the same
reason.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_network import PERIODS, read_csv  # noqa: E402
from common import ensure_dir  # noqa: E402
from labels import LANGS, localise  # noqa: E402
from make_figures import (  # noqa: E402
    FIG_DIR, PALETTE, ROOT, draw_network, esc, normalise, radius,
    svg_document, trim_to_width,
)
from make_descriptive_figures import (  # noqa: E402
    AXIS_FONT, BAR_GAP, PERIOD_LABEL, VALUE_FONT, _axis_text, _fmt, _grid_line,
    _table_html, columns, hbars, series, stacked,
)

PROC = os.path.join(ROOT, "data", "processed")

# How many source nodes the shortest-path sample runs BFS from. The whole
# giant component is 5,776 firms; an all-pairs BFS is 5,776 traversals and
# roughly ten minutes, and the distribution is flat to the third decimal well
# before 200. Fixed rather than tuned, so the figure does not move when the
# machine gets faster.
PATH_SAMPLE = 200
PATH_SEED = 11
LOUVAIN_SEED = 7

# Territories shown by name in the two figures that break composition down by
# one. Four plus "other" is the five-slot adjacent-pairlist the palette
# validates for stacks; the fifth slot is not a territory, it is the residue.
TOP_TERR = 4

# The catalogue's heading for a firm it does not place in any single territory.
# It is the modal label in almost every community, which makes it useless as a
# colour and important as a caveat.
NON_TERRITORY = "Empire (transversal)"


# --- loading --------------------------------------------------------------
def _terr(rec: dict) -> str:
    return (rec.get("countries") or rec.get("regions") or "").split("; ")[0]


def _pct(lang: str):
    """Percent formatter for a value already in 0-100, decimal comma in French.

    A value that rounds to zero without being zero prints as "< 0.1%", not as
    "0%": three of the path-length bars hold a real if tiny share of the pairs,
    and labelling them "0%" says the distance never occurs.
    """
    def fmt(v: float) -> str:
        if 0 < v < 0.05:
            s = "< 0.1%"
        elif abs(v - round(v)) < 0.05:
            s = f"{v:.0f}%"
        else:
            s = f"{v:.1f}%"
        return s.replace(".", ",") if lang == "fr" else s
    return fmt


def _num(v: float, lang: str, places: int = 2) -> str:
    """A decimal in prose, with the language's own separator."""
    s = f"{v:.{places}f}"
    return s.replace(".", ",") if lang == "fr" else s


def _p(frac: float, lang: str, places: int = 1) -> str:
    """A 0-1 share as prose. French writes 98,5 %, not 98.5%, and a caption
    that says 98.5% beside a bar labelled 98,5 % reads as two numbers."""
    s = f"{frac:.{places}%}"
    return s.replace(".", ",").replace("%", " %") if lang == "fr" else s


def load_graph():
    """The company interlock graph, with each edge's shared directors kept.

    Built by iterating the CSV in file order, which is a committed total sort,
    so the node insertion order is fixed. Louvain iterates nodes in that order,
    so the partition is a function of the data and the seed and nothing else.
    """
    import networkx as nx

    G = nx.Graph()
    for e in read_csv("edges_company_interlock.csv"):
        G.add_edge(e["company_id_1"], e["company_id_2"],
                   weight=int(e["weight"]),
                   directors=tuple(x for x in e["shared_directors"].split("; ") if x))
    return G


def sorted_components(G) -> list[list[str]]:
    import networkx as nx

    return sorted((sorted(c) for c in nx.connected_components(G)),
                  key=lambda c: (-len(c), c[0]))


def louvain(G) -> list[list[str]]:
    """Communities, largest first, each one sorted, ties broken by first member."""
    import networkx as nx

    parts = nx.community.louvain_communities(G, seed=LOUVAIN_SEED, weight="weight")
    return sorted((sorted(c) for c in parts), key=lambda c: (-len(c), c[0]))


def gather(lang: str) -> dict:
    """Every structural measurement the ten figures need, computed once."""
    import networkx as nx

    comp = {c["company_id"]: c for c in read_csv("companies.csv")}
    G = load_graph()

    comps = sorted_components(G)
    giant = comps[0]
    H = G.subgraph(giant)

    # Degree distributions, full graph and the weight >= 2 graph. The second is
    # the point of the figure: 84% of edges rest on one shared director, so the
    # first curve is partly a picture of that fragility rather than of the
    # elite's connectivity.
    deg_all = Counter(dict(G.degree()).values())
    G2 = nx.Graph((u, v, d) for u, v, d in G.edges(data=True) if d["weight"] >= 2)
    deg_2 = Counter(dict(G2.degree()).values())

    core = nx.core_number(G)
    shells: dict[int, list[str]] = defaultdict(list)
    for n in sorted(core):
        shells[core[n]].append(n)
    shell_density = {k: nx.density(G.subgraph(v)) for k, v in shells.items()}

    # Robustness: the giant component as the edge filter tightens.
    thresholds = []
    for w in range(1, 9):
        K = nx.Graph((u, v, d) for u, v, d in G.edges(data=True) if d["weight"] >= w)
        big = max((len(c) for c in nx.connected_components(K)), default=0)
        thresholds.append({"w": w, "nodes": K.number_of_nodes(),
                           "edges": K.number_of_edges(), "giant": big,
                           "share": big / G.number_of_nodes()})

    # Shortest paths, sampled. Sorted source list plus an explicit RNG: the
    # obvious `random.sample(giant_set, k)` samples from a set and lands on a
    # different 200 firms each process.
    rng = random.Random(PATH_SEED)
    sources = rng.sample(giant, min(PATH_SAMPLE, len(giant)))
    paths = Counter()
    for s in sorted(sources):
        for d in nx.single_source_shortest_path_length(H, s).values():
            if d:
                paths[d] += 1

    parts = louvain(G)
    comm_terr = []
    for c in parts:
        counts = Counter(_terr(comp.get(n, {})) or "" for n in c)
        comm_terr.append(counts)
    # Interlocks between communities, for the backbone drawing.
    where = {n: i for i, c in enumerate(parts) for n in c}
    between = Counter()
    for u, v, d in G.edges(data=True):
        a, b = where[u], where[v]
        if a != b:
            between[(min(a, b), max(a, b))] += d["weight"]

    # Cross-territory interlocks, overall and per period.
    def crossing(rows, a_key, b_key):
        within = across = unknown = 0
        for r in rows:
            a, b = _terr(comp.get(r[a_key], {})), _terr(comp.get(r[b_key], {}))
            if not a or not b:
                unknown += 1
            elif a == b:
                within += 1
            else:
                across += 1
        return within, across, unknown

    cross_all = crossing(read_csv("edges_company_interlock.csv"),
                         "company_id_1", "company_id_2")
    by_period_rows = defaultdict(list)
    for r in read_csv("edges_company_interlock_by_period.csv"):
        by_period_rows[r["period"]].append(r)
    cross_period = {p: crossing(rs, "company_id_1", "company_id_2")
                    for p, rs in by_period_rows.items()}

    # Individual reach: distinct firms and distinct territories per person.
    seats = defaultdict(set)
    for e in read_csv("edges_person_company.csv"):
        if e["is_board_seat"] == "1":
            seats[e["person_id"]].add(e["company_id"])
    reach = []
    for pid in sorted(seats):
        firms = sorted(seats[pid])
        terrs = sorted({_terr(comp.get(f, {})) for f in firms} - {""})
        reach.append({"person_id": pid, "n_firms": len(firms),
                      "n_terr": len(terrs), "terrs": terrs})
    reach.sort(key=lambda r: (-r["n_terr"], -r["n_firms"], r["person_id"]))

    # Structure per period, from that period's own edge slice.
    per_period = []
    for name, _, _ in PERIODS:
        rows = by_period_rows.get(name, [])
        K = nx.Graph()
        for r in rows:
            K.add_edge(r["company_id_1"], r["company_id_2"], weight=int(r["weight"]))
        n = K.number_of_nodes()
        big = max((len(c) for c in nx.connected_components(K)), default=0)
        per_period.append({
            "period": name, "firms": n, "edges": K.number_of_edges(),
            "mean_degree": (2 * K.number_of_edges() / n) if n else 0.0,
            "giant_share": (big / n) if n else 0.0,
        })

    return {
        "G": G, "comp": comp, "comps": comps, "giant": giant,
        "deg_all": deg_all, "deg_2": deg_2,
        "n_nodes_2": G2.number_of_nodes(), "n_edges_2": G2.number_of_edges(),
        "core": core, "shells": shells, "shell_density": shell_density,
        "thresholds": thresholds, "paths": paths, "n_sources": len(sources),
        "parts": parts, "comm_terr": comm_terr, "between": between,
        "cross_all": cross_all, "cross_period": cross_period,
        "reach": reach, "per_period": per_period,
        "assortativity": nx.degree_assortativity_coefficient(G),
        "clustering": nx.average_clustering(G),
        "transitivity": nx.transitivity(G),
        "modularity": nx.community.modularity(G, [set(c) for c in parts],
                                              weight="weight"),
        "lang": lang,
    }


# --- extra chart primitives ----------------------------------------------
def loglog(curves, width, height, mode, x_title="", y_title=""):
    """Step lines on log-log axes: the form for a heavy-tailed distribution.

    A degree distribution spanning 1 to 499 on a linear axis is a spike at the
    origin and nothing else. Bars are wrong here for a second reason: a CCDF is
    a monotone *function* of a continuous threshold, not a set of counts in
    bins, and drawing it as bars invites the reader to compare bar heights that
    are cumulative and therefore not independent.

    `curves` are `(label, colour, [(x, y), ...])` with x, y strictly positive.
    """
    # The right margin holds the direct end labels in full. Trimming them to a
    # narrower gutter left "≥ 2 admini…", which is a label that identifies
    # nothing and throws the reader back on colour alone.
    left, bottom, top, right = 58.0, 42.0, 16.0, 214.0
    plot_w, plot_h = width - left - right, height - bottom - top
    xs = [x for _, _, pts in curves for x, _ in pts]
    ys = [y for _, _, pts in curves for _, y in pts]
    x_hi = 10 ** math.ceil(math.log10(max(xs)))
    y_lo = 10 ** math.floor(math.log10(min(ys)))
    y_hi = 1.0

    def px(x):
        return left + plot_w * math.log10(max(x, 1.0)) / math.log10(x_hi)

    def py(y):
        span = math.log10(y_hi) - math.log10(y_lo)
        return top + plot_h * (1 - (math.log10(y) - math.log10(y_lo)) / span)

    parts = []
    for k in range(int(math.log10(y_lo)), 1):
        yt = py(10.0 ** k)
        parts.append(_grid_line(mode, left, yt, left + plot_w, yt))
        # Percentages all the way down rather than "10^-4" for the last two
        # decades: the axis measures a share, and a reader who has to convert
        # scientific notation back into a share is reading arithmetic.
        label = f"{10.0 ** k:.{max(0, -k - 2)}%}"
        parts.append(_axis_text(mode, left - 8, yt + 3.6, label, "end", muted=True))
    for k in range(0, int(math.log10(x_hi)) + 1):
        xt = px(10 ** k)
        parts.append(_grid_line(mode, xt, top, xt, top + plot_h))
        parts.append(_axis_text(mode, xt, top + plot_h + 15, _fmt(10 ** k),
                                "middle", muted=True))
    for label, colour, pts in curves:
        # Step-after: the CCDF is constant between observed degrees, and
        # joining the points with straight segments would invent values there.
        d = [f"M{px(pts[0][0]):.1f} {py(pts[0][1]):.1f}"]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            d.append(f"H{px(x1):.1f}V{py(y1):.1f}")
        parts.append(f'<path d="{"".join(d)}" fill="none" stroke="{colour}" '
                     f'stroke-width="2" stroke-linejoin="round"/>')
        # Direct label at the curve's end, so identity never rests on colour.
        ex, ey = pts[-1]
        parts.append(_axis_text(mode, px(ex) + 9, py(ey) + 3.6,
                                trim_to_width(label, VALUE_FONT,
                                              width - px(ex) - 12),
                                "start", VALUE_FONT))
    parts.append(_grid_line(mode, left, top + plot_h, left + plot_w, top + plot_h))
    if y_title:
        parts.append(_axis_text(mode, 0, top - 5, y_title, "start", muted=True))
    if x_title:
        parts.append(_axis_text(mode, left + plot_w, top + plot_h + 32, x_title,
                                "end", muted=True))
    return "".join(parts)


def mini_columns(panels, width, height, mode):
    """One small column chart per metric, side by side, each on its own scale.

    Four measures in four different units cannot share a value axis, and the
    alternative — one chart with two y-axes — is the single worst thing a chart
    can do. Small multiples give each measure an honest scale and still let the
    eye compare *shapes* across the row, which is the actual question.
    """
    p = PALETTE[mode]
    n = len(panels)
    gap = 26.0
    pw = (width - gap * (n - 1)) / n
    top, bottom = 34.0, 34.0
    ph = height - top - bottom
    out = []
    for i, (title, rows, fmt) in enumerate(panels):
        ox = i * (pw + gap)
        hi = max((v for _, v in rows), default=1) or 1
        out.append(f'<g transform="translate({ox:.1f},0)">')
        out.append(f'<text x="0" y="12" font-size="{AXIS_FONT + 1:.1f}" '
                   f'font-weight="600" font-family="ui-sans-serif,system-ui,sans-serif" '
                   f'fill="{p["text_primary"]}">{esc(title)}</text>')
        out.append(_grid_line(mode, 0, top + ph, pw, top + ph))
        step = pw / max(len(rows), 1)
        bw = max(step - BAR_GAP * 3, 3.0)
        for j, (label, value) in enumerate(rows):
            bh = ph * (value / hi)
            x = j * step + (step - bw) / 2
            out.append(
                f'<g class="mk"><title>{esc(f"{label}: {fmt(value)}")}</title>'
                f'<rect x="{x:.1f}" y="{top + ph - bh:.1f}" width="{bw:.1f}" '
                f'height="{max(bh, 1.0):.1f}" rx="4" fill="{p["series"][0]}"/></g>'
            )
            out.append(_axis_text(mode, x + bw / 2, top + ph - bh - 5, fmt(value),
                                  "middle", VALUE_FONT - 1))
            out.append(_axis_text(mode, x + bw / 2, top + ph + 15, label, "middle",
                                  AXIS_FONT - 1.5, muted=True))
        out.append("</g>")
    return "".join(out)


# --- the ten figures ------------------------------------------------------
def fig_degree_distribution(d, mode, lang):
    cols = series(mode, 2)

    def ccdf(dist):
        total = sum(dist.values())
        pts, seen = [], 0
        for k in sorted(dist):
            if k <= 0:
                seen += dist[k]
                continue
            pts.append((k, (total - seen) / total))
            seen += dist[k]
        return pts

    a, b = ccdf(d["deg_all"]), ccdf(d["deg_2"])
    lab = {"fr": ("tous les liens", "≥ 2 administrateurs partagés"),
           "en": ("all edges", "≥ 2 shared directors")}[lang]
    body = loglog([(lab[0], cols[0], a), (lab[1], cols[1], b)], 1040, 430, mode,
                  x_title={"fr": "degré (nombre de firmes interconnectées)",
                           "en": "degree (firms interlocked with)"}[lang],
                  y_title={"fr": "part des firmes de degré ≥ k",
                           "en": "share of firms with degree ≥ k"}[lang])
    hi_all = max(d["deg_all"])
    hi_2 = max(d["deg_2"])
    cap = {
        "fr": (f"Distribution complémentaire cumulée du degré, en échelles "
               f"logarithmiques. Le degré maximal passe de {hi_all} à {hi_2} "
               f"lorsqu'on exige deux administrateurs partagés au lieu d'un : "
               f"la connectivité extrême du graphe complet est en grande partie "
               f"faite de liens à un seul nom. Les deux courbes s'infléchissent "
               f"vers le bas plutôt que de suivre une droite : la queue est plus "
               f"courte qu'une loi de puissance, il y a donc une échelle "
               f"caractéristique — ce réseau n'est pas « sans échelle », et un "
               f"exposant ajusté sur ces données décrirait la source autant que "
               f"la structure (voir figure 8)."),
        "en": (f"Complementary cumulative degree distribution, both axes "
               f"logarithmic. Maximum degree falls from {hi_all} to {hi_2} once "
               f"two shared directors are required instead of one: much of the "
               f"full graph's extreme connectivity is made of single-name edges. "
               f"Both curves bend downward rather than running straight: the "
               f"tail is shorter than a power law's, so there is a "
               f"characteristic scale — this network is not “scale-free”, and an "
               f"exponent fitted to it would describe the source as much as the "
               f"structure (figure 8)."),
    }[lang]
    title = {"fr": "Distribution du degré", "en": "Degree distribution"}[lang]
    legend = list(zip(cols, lab))
    # Every degree either curve reaches gets a row, with 0 where the other one
    # does not: dropping the rows missing from the first curve would silently
    # shorten the table against the figure it is the relief for.
    ta, tb = dict(a), dict(b)
    tbl = ([Hn(lang, "degree"), Hn(lang, "share_all"), Hn(lang, "share_2")],
           [[k, f"{ta.get(k, 0):.4f}", f"{tb.get(k, 0):.4f}"]
            for k in sorted(set(ta) | set(tb))])
    return body, 430, title, legend, cap, tbl


def fig_kcore_profile(d, mode, lang):
    cols = series(mode, 2)
    shells = d["shells"]
    ks = sorted(shells)
    # One column per integer k, not per *occupied* k. Only occupied shells make
    # a column, but the empty ones still take up their slot: with the gaps
    # closed up, k=46 and k=71 sat side by side and the 24 empty levels between
    # them — the thing that says the deep core is detached from the rest of the
    # graph — read as a smooth continuation.
    rows = []
    for k in range(1, ks[-1] + 1):
        n = len(shells.get(k, ()))
        dens = d["shell_density"].get(k, 0.0)
        clique = n >= 10 and dens > 0.999
        tip = (f"k={k}: {_fmt(n)} " + ("firmes" if lang == "fr" else "firms")
               + f", {'densité' if lang == 'fr' else 'density'} {dens:.3f}")
        # A decade tick within a few columns of the last one collides with it:
        # k=70 is empty, and its label printed hard against "71".
        tick = k in (1, ks[-1]) or (k % 10 == 0 and abs(k - ks[-1]) >= 4)
        rows.append((str(k) if tick else "", n, tip,
                     cols[1] if clique else cols[0]))
    body = columns(rows, 1040, 400, mode, log=True,
                   y_title={"fr": "firmes (log)", "en": "firms (log)"}[lang],
                   x_title={"fr": "numéro de cœur (k)", "en": "core number (k)"}[lang])
    cliques = [k for k in ks
               if len(shells[k]) >= 10 and d["shell_density"][k] > 0.999]
    kmax = ks[-1]
    cap = {
        "fr": (f"Firmes par coquille de k-cœur : une firme est au niveau k si "
               f"elle a k voisins qui en ont eux-mêmes k. Le profil devrait "
               f"décroître régulièrement ; il ne le fait pas. Les coquilles "
               f"{', '.join('k=' + str(k) for k in cliques)} sont des graphes "
               f"*complets* — chaque firme y est liée à toutes les autres, ce "
               f"qu'aucun conseil d'administration réel ne produit. Ce sont des "
               f"notices fusionnées et des mandats cumulés, que seule cette "
               f"décomposition rend visibles. Les niveaux vides entre k=46 et "
               f"k={kmax} sont réels : rien n'occupe ce palier, le cœur profond "
               f"est détaché du reste du graphe. La figure 26 le démonte."),
        "en": (f"Firms per k-core shell: a firm is at level k if it has k "
               f"neighbours that themselves have k. The profile should decay "
               f"smoothly; it does not. Shells "
               f"{', '.join('k=' + str(k) for k in cliques)} are *complete* "
               f"graphs — every firm in them tied to every other, which no real "
               f"board produces. They are merged notices and accumulated "
               f"directorships, and this decomposition is the only thing that "
               f"makes them visible. The empty levels between k=46 and k={kmax} "
               f"are real: nothing occupies that band, so the deep core stands "
               f"off from the rest of the graph. Figure 26 takes it apart."),
    }[lang]
    title = {"fr": f"Décomposition en k-cœurs (k max = {kmax})",
             "en": f"k-core decomposition (max k = {kmax})"}[lang]
    legend = [(cols[0], {"fr": "coquille ordinaire", "en": "ordinary shell"}[lang]),
              (cols[1], {"fr": "graphe complet (artefact)",
                         "en": "complete graph (artefact)"}[lang])]
    tbl = ([Hn(lang, "k"), Hn(lang, "firms"), Hn(lang, "density")],
           [[k, len(shells[k]), f"{d['shell_density'][k]:.3f}"] for k in ks])
    return body, 400, title, legend, cap, tbl


COMM_W, COMM_H = 1340.0, 620.0


def fig_community_backbone(d, mode, lang):
    """Communities as nodes: which clusters of firms touch which.

    Drawn rather than charted because the claim is about adjacency. Fourteen
    nodes is small enough that a node-link diagram is read rather than
    squinted at, which is exactly the condition under which one is the right
    form — the 5,862-firm version of this picture is figure 4, and it is a
    texture, not a reading.
    """
    import networkx as nx

    p = PALETTE[mode]
    parts = d["parts"][:14]
    keep = set(range(len(parts)))
    B = nx.Graph()
    for i in sorted(keep):
        B.add_node(i)
    for (a, b), w in sorted(d["between"].items()):
        if a in keep and b in keep:
            B.add_edge(a, b, weight=w)
    pos = normalise(nx.spring_layout(B, k=1.9 / math.sqrt(max(len(parts), 1)),
                                     iterations=300, seed=5, weight="weight"),
                    COMM_W, COMM_H, pad=64, pad_x=250.0)

    # The modal territory label, ignoring "Empire (transversal)". That value is
    # the catalogue's heading for a firm it declines to place in one territory,
    # so it is the mode almost everywhere - and colouring by it would paint most
    # of the diagram one hue and say nothing. Same call as excluding "Documents
    # généraux" from the sector chart: a filing convention is not a category.
    terr_of = []
    for i in sorted(keep):
        counts = {t: n for t, n in d["comm_terr"][i].items()
                  if t and t != NON_TERRITORY}
        best = max(sorted(counts), key=lambda t: (counts[t], t)) if counts else ""
        terr_of.append(best)
    top3 = [t for t, _ in Counter(terr_of).most_common(3) if t]
    slot = {t: i for i, t in enumerate(top3)}

    # Genuinely area-proportional: r = R x sqrt(size / max). The shared
    # `radius()` helper takes the square root of a value first rescaled to
    # 0-1 across the drawn set, which is right where the caption says "bigger
    # means more" and wrong here, where it says "area is the firm count" - over
    # a 191-611 range that rescaling turns a 3.2x difference into a 20x
    # difference in area, and the caption would be a false statement.
    hi = max(len(c) for c in parts)
    nodes = []
    for i in sorted(keep):
        t = terr_of[i]
        nodes.append({
            "id": f"C{i + 1}",
            "label": (f"C{i + 1} · {localise(t, lang) or '—'} "
                      f"({_fmt(len(parts[i]))})"),
            "x": pos[i][0], "y": pos[i][1],
            "r": 30.0 * math.sqrt(len(parts[i]) / hi),
            "color": p["series"][slot[t]] if t in slot else p["other"],
        })
    # Edge weights here are thousands of interlocks, not counts of directors,
    # so they are rescaled into the 1-8 band `draw_network` expects rather than
    # passed raw, which would make every edge the maximum width.
    ew = [w for (a, b), w in d["between"].items() if a in keep and b in keep]
    w_hi = max(ew) if ew else 1
    edges = [(pos[a], pos[b], 1 + 7 * (w / w_hi))
             for (a, b), w in sorted(d["between"].items())
             if a in keep and b in keep]
    body = draw_network(nodes, edges, COMM_W, COMM_H, mode, label_top=len(nodes),
                        font=11.5, label_margin=250.0, edge_opacity=1.6,
                        node_ring=2.0)
    cap = {
        "fr": (f"Les {len(parts)} plus grandes communautés de Louvain, chacune "
               f"un nœud dont l'aire est son nombre de firmes et la couleur son "
               f"territoire dominant ; l'épaisseur d'un lien est le nombre "
               f"d'administrateurs partagés entre deux communautés. Modularité "
               f"{_num(d['modularity'], lang)} — une partition réelle, mais aucun bloc "
               f"n'est isolé : le réseau se regroupe sans se cliver. Le "
               f"territoire dominant est calculé hors « Empire (transversal) », "
               f"qui est le label majoritaire presque partout et n'est pas un "
               f"territoire mais l'aveu que la source n'en désigne aucun."),
        "en": (f"The {len(parts)} largest Louvain communities, each a node whose "
               f"area is its firm count and whose colour is its dominant "
               f"territory; edge width is the number of shared directors "
               f"between two communities. Modularity {d['modularity']:.2f} — a "
               f"real partition, but no block stands apart: the network "
               f"clusters without cleaving. The dominant territory is taken "
               f"excluding “Empire (transversal)”, which is the majority label "
               f"almost everywhere and is not a territory but the source's "
               f"admission that it names none."),
    }[lang]
    title = {"fr": "Ossature entre communautés",
             "en": "Backbone between communities"}[lang]
    legend = [(p["series"][slot[t]], localise(t, lang)) for t in top3]
    legend.append((p["other"], {"fr": "autre territoire",
                                "en": "other territory"}[lang]))
    tbl = ([Hn(lang, "community"), Hn(lang, "firms"), Hn(lang, "terr_dom")],
           [[f"C{i + 1}", len(parts[i]), localise(terr_of[i], lang) or "—"]
            for i in sorted(keep)])
    return body, COMM_H, title, legend, cap, tbl


def fig_giant_vs_threshold(d, mode, lang):
    rows = [(str(t["w"]), t["share"] * 100,
             f"w ≥ {t['w']}: {_fmt(t['giant'])} "
             f"{'firmes' if lang == 'fr' else 'firms'} "
             f"({_p(t['share'], lang)}), {_fmt(t['edges'])} "
             f"{'liens' if lang == 'fr' else 'edges'}")
            for t in d["thresholds"]]
    body = columns(rows, 1040, 380, mode, hi=100.0, max_bar=64.0,
                   value_fmt=_pct(lang), tick_fmt=_pct(lang),
                   y_title={"fr": "part des firmes dans la composante géante",
                            "en": "share of firms in the giant component"}[lang],
                   x_title={"fr": "administrateurs partagés exigés",
                            "en": "shared directors required"}[lang])
    two = d["thresholds"][1]
    one = d["thresholds"][0]
    cap = {
        "fr": (f"Composante géante en fonction du seuil de poids. À un "
               f"administrateur partagé, {_p(one['share'], lang)} des firmes forment "
               f"une seule composante ; à deux, {_p(two['share'], lang)}. Le réseau "
               f"« connecté » de la figure 4 est donc tenu par des liens à un "
               f"seul nom, dont chacun disparaît si la résolution d'entité se "
               f"trompe une fois. Toute analyse de composante ou de distance "
               f"doit indiquer son seuil."),
        "en": (f"Giant component against the weight threshold. At one shared "
               f"director {_p(one['share'], lang)} of firms form a single component; "
               f"at two, {_p(two['share'], lang)}. The “connected” network of figure 4 "
               f"is therefore held together by single-name edges, each of which "
               f"vanishes on one entity-resolution error. Any component or "
               f"distance analysis has to state its threshold."),
    }[lang]
    title = {"fr": "Ce qui reste quand on exige plus qu'un nom",
             "en": "What survives when one name is not enough"}[lang]
    tbl = ([Hn(lang, "w"), Hn(lang, "firms"), Hn(lang, "edges"), Hn(lang, "giant")],
           [[t["w"], t["nodes"], t["edges"], f"{t['share']:.1%}"]
            for t in d["thresholds"]])
    return body, 380, title, None, cap, tbl


def fig_path_lengths(d, mode, lang):
    total = sum(d["paths"].values())
    ks = sorted(d["paths"])
    rows = [(str(k), d["paths"][k] / total * 100,
             f"{k}: {_p(d['paths'][k] / total, lang)}") for k in ks]
    body = columns(rows, 1040, 360, mode, hi=100.0, max_bar=64.0,
                   value_fmt=_pct(lang), tick_fmt=_pct(lang),
                   y_title={"fr": "part des paires", "en": "share of pairs"}[lang],
                   x_title={"fr": "distance (liens d'interlock)",
                            "en": "distance (interlock steps)"}[lang])
    mean = sum(k * v for k, v in d["paths"].items()) / total
    cap = {
        "fr": (f"Distribution des plus courts chemins dans la composante géante, "
               f"à partir de {d['n_sources']} firmes tirées au sort (graine fixe). "
               f"Distance moyenne {_num(mean, lang)}, maximum observé {max(ks)} : "
               f"n'importe quelles deux des {_fmt(len(d['giant']))} firmes de la "
               f"composante sont à trois poignées de main l'une de l'autre. "
               f"À lire avec la figure 21 — cette petitesse est celle du graphe "
               f"à un seul administrateur partagé."),
        "en": (f"Shortest-path distribution inside the giant component, from "
               f"{d['n_sources']} randomly drawn firms (fixed seed). Mean "
               f"distance {_num(mean, lang)}, longest observed {max(ks)}: any two of the "
               f"{_fmt(len(d['giant']))} firms in the component are about three "
               f"handshakes apart. Read it against figure 21 — this smallness "
               f"is the smallness of the one-shared-director graph."),
    }[lang]
    title = {"fr": "À quelle distance sont deux firmes",
             "en": "How far apart two firms are"}[lang]
    tbl = ([Hn(lang, "distance"), Hn(lang, "pairs"), Hn(lang, "pct")],
           [[k, d["paths"][k], f"{d['paths'][k] / total:.1%}"] for k in ks])
    return body, 360, title, None, cap, tbl


def fig_community_territory(d, mode, lang):
    parts = d["parts"][:12]
    counts = [d["comm_terr"][i] for i in range(len(parts))]
    overall = Counter()
    for c in counts:
        overall.update(c)
    overall.pop("", None)
    top = [t for t, _ in sorted(overall.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_TERR]]
    other = {"fr": "autres / non renseigné", "en": "other / unrecorded"}[lang]
    keys = top + [other]
    groups = []
    for i, c in enumerate(counts):
        row = {t: c.get(t, 0) for t in top}
        row[other] = sum(v for t, v in c.items() if t not in top)
        groups.append((f"C{i + 1}", row))
    body = stacked(groups, 1040, 400, mode, keys,
                   lambda k: localise(k, lang) if k != other else other, share=True)
    purity = max(
        max(g[1].values()) / max(sum(g[1].values()), 1) for g in groups)
    cap = {
        "fr": (f"Composition territoriale des douze plus grandes communautés. "
               f"Aucune n'est territorialement pure : la plus homogène plafonne "
               f"à {_p(purity, lang, 0)}, et la catégorie « Empire (transversal) » est "
               f"partout. Les groupes d'interlocks ne suivent pas les frontières "
               f"coloniales — ils suivent des groupes financiers, dont c'était "
               f"précisément la vocation d'enjamber ces frontières."),
        "en": (f"Territorial composition of the twelve largest communities. None "
               f"is territorially pure: the most homogeneous tops out at "
               f"{_p(purity, lang, 0)}, and “Empire (transversal)” is present throughout. "
               f"Interlock clusters do not follow colonial borders — they follow "
               f"financial groups, whose whole purpose was to straddle those "
               f"borders."),
    }[lang]
    title = {"fr": "Les communautés suivent-elles les territoires ?",
             "en": "Do communities follow territories?"}[lang]
    legend = list(zip(series(mode, len(keys)),
                      [localise(k, lang) if k != other else other for k in keys]))
    tbl = ([Hn(lang, "community")] + [localise(k, lang) if k != other else other
                                      for k in keys],
           [[n] + [c.get(k, 0) for k in keys] for n, c in groups])
    return body, 400, title, legend, cap, tbl


def fig_cross_territory(d, mode, lang):
    rows = []
    for name, _, _ in PERIODS:
        w, a, _u = d["cross_period"].get(name, (0, 0, 0))
        if not (w + a):
            continue
        rows.append((PERIOD_LABEL[name], a / (w + a) * 100,
                     f"{PERIOD_LABEL[name]}: {_fmt(a)} / {_fmt(w + a)}"))
    body = columns(rows, 1040, 360, mode, hi=100.0, max_bar=64.0,
                   value_fmt=_pct(lang), tick_fmt=_pct(lang),
                   y_title={"fr": "part des interlocks franchissant une frontière",
                            "en": "share of interlocks crossing a border"}[lang])
    w, a, _u = d["cross_all"]
    cap = {
        "fr": (f"Part des liens d'interlock unissant deux firmes rattachées à "
               f"des territoires différents. Sur l'ensemble du graphe, "
               f"{_p(a / (w + a), lang)}. La part décroît régulièrement d'une période à "
               f"la suivante, mais la composition des sources change en même "
               f"temps (figure 9) : la tendance est réelle dans les données, "
               f"elle n'est pas pour autant établie comme une tendance "
               f"historique."),
        "en": (f"Share of interlock edges joining two firms filed under "
               f"different territories. Across the whole graph, {_p(a / (w + a), lang)}. "
               f"The share falls steadily from one period to the next, but the "
               f"source mix changes over the same span (figure 9): the trend is "
               f"real in the data without thereby being established as a "
               f"historical one."),
    }[lang]
    title = {"fr": "Interlocks franchissant une frontière coloniale",
             "en": "Interlocks that cross a colonial border"}[lang]
    tbl = ([Hn(lang, "period"), Hn(lang, "across"), Hn(lang, "within"), Hn(lang, "pct")],
           [[PERIOD_LABEL[n], d["cross_period"][n][1], d["cross_period"][n][0],
             f"{d['cross_period'][n][1] / max(sum(d['cross_period'][n][:2]), 1):.1%}"]
            for n, _, _ in PERIODS if d["cross_period"].get(n)])
    return body, 360, title, None, cap, tbl


SPAN_FLOOR = 8


def fig_person_reach(d, mode, lang):
    """Who spans the empire, ranked by seats rather than by territories.

    Ranking by territories and drawing that as the bar was the first version
    and it is a bad chart: the eighteen widest-reaching people span 8 to 11
    territories, so eighteen near-identical bars carry the ranking and nothing
    else. The selection is the territory span - stated in the title, since a
    selection rule belongs in words - and the length is the seat count, which
    runs 18 to 72 and is the quantity that actually varies.
    """
    wide = [r for r in d["reach"] if r["n_terr"] >= SPAN_FLOOR]
    top = sorted(wide, key=lambda r: (-r["n_firms"], r["person_id"]))[:18]
    firms = {"fr": "firmes", "en": "firms"}[lang]
    terr = {"fr": "territoires", "en": "territories"}[lang]
    rows = [(f'{r["person_id"]} · {r["n_terr"]}', r["n_firms"],
             f"{r['person_id']}: {r['n_firms']} {firms}, {r['n_terr']} {terr} — "
             + ", ".join(localise(t, lang) for t in r["terrs"][:6]))
            for r in top]
    body, h = hbars(rows, 1040, mode, label_w=250.0,
                    top_note={"fr": f"sièges détenus · {terr} après le point médian",
                              "en": f"board seats held · {terr} after the dot"}[lang])
    dist = Counter(r["n_terr"] for r in d["reach"])
    one = dist[1] / sum(dist.values())
    cap = {
        "fr": (f"Les {len(wide)} personnes présentes dans au moins "
               f"{SPAN_FLOOR} territoires distincts ; les 18 qui détiennent le "
               f"plus de sièges sont montrées, par identifiant tel qu'il figure "
               f"dans le jeu de données. La barre est le nombre de firmes, le "
               f"nombre après le point médian celui des territoires. "
               f"{_p(one, lang, 0)} des administrateurs n'apparaissent "
               f"que dans un seul territoire : la poignée qui en couvre huit ou "
               f"plus est l'ossature humaine de la figure 24. Trois de ces "
               f"identifiants — « paris », « laurent », « a-paris-c » — sont des "
               f"résidus d'extraction et non des personnes : un nom de famille "
               f"seul que la résolution n'a pas pu rattacher, et un lieu pris "
               f"pour un nom. Ils restent visibles ici plutôt que filtrés en "
               f"silence, parce qu'un pseudo-acteur qui occupe une position "
               f"structurale réelle est ce que le lecteur doit savoir."),
        "en": (f"The {len(wide)} people appearing in at least {SPAN_FLOOR} "
               f"distinct territories; the 18 holding the most seats are shown, "
               f"by identifier as the dataset records it. The bar is the firm "
               f"count, the number after the dot the territory count. {_p(one, lang, 0)} "
               f"of directors appear in one territory only: the handful spanning "
               f"eight or more are the human frame of figure 24. Three of these "
               f"identifiers — “paris”, “laurent”, “a-paris-c” — are extraction "
               f"residue rather than people: a bare surname resolution could not "
               f"attach, and a place read as a name. They stay visible rather "
               f"than being filtered out silently, because a pseudo-actor "
               f"holding a real structural position is the thing a reader needs "
               f"to know."),
    }[lang]
    title = {"fr": f"Portée individuelle : sièges de ceux qui couvrent "
                   f"{SPAN_FLOOR} territoires ou plus",
             "en": f"Individual reach: seats held by those spanning "
                   f"{SPAN_FLOOR} territories or more"}[lang]
    tbl = ([Hn(lang, "person"), Hn(lang, "terr_n"), Hn(lang, "firms")],
           [[r["person_id"], r["n_terr"], r["n_firms"]] for r in top])
    return body, h + 8, title, None, cap, tbl


CORE_PANEL_W, CORE_PANEL_H = 620.0, 520.0
PANEL_INSET = 8.0
HOLDER = "homberg-o"


def fig_innermost_core(d, mode, lang):
    """The deepest k-core, as observed and with one director's edges removed.

    Two panels on one shared layout and one shared size scale, so the only
    thing that differs between them is the edge set — which is the finding.
    Recomputing the layout for the second panel would move every node and let
    a reader attribute the change to anything.
    """
    import networkx as nx

    p = PALETTE[mode]
    G = d["G"]
    kmax = max(d["core"].values())
    inner = sorted(n for n, k in d["core"].items() if k == kmax)
    S = set(inner)

    full = nx.Graph()
    full.add_nodes_from(inner)
    reduced = nx.Graph()
    reduced.add_nodes_from(inner)
    for u, v, attr in sorted(G.edges(data=True), key=lambda e: (e[0], e[1])):
        if u in S and v in S:
            full.add_edge(u, v, weight=attr["weight"])
            rest = [x for x in attr["directors"] if x != HOLDER]
            if rest:
                reduced.add_edge(u, v, weight=len(rest))

    # A complete graph has no layout worth computing — every arrangement is
    # equally "correct" — so both panels use a circle, which is the honest
    # drawing of a clique and keeps every node at a fixed, comparable place.
    pos = {}
    for i, n in enumerate(inner):
        ang = 2 * math.pi * i / len(inner) - math.pi / 2
        pos[n] = (CORE_PANEL_W / 2 + math.cos(ang) * (CORE_PANEL_W / 2 - 34),
                  CORE_PANEL_H / 2 + math.sin(ang) * (CORE_PANEL_H / 2 - 34))

    surv = reduced.number_of_edges()
    kept_core = max(nx.core_number(reduced).values()) if surv else 0
    labels = {
        "fr": (f"tel qu'observé — {_fmt(full.number_of_edges())} liens, k = {kmax}",
               f"sans {HOLDER} — {_fmt(surv)} liens, k = {kept_core}"),
        "en": (f"as observed — {_fmt(full.number_of_edges())} edges, k = {kmax}",
               f"without {HOLDER} — {_fmt(surv)} edges, k = {kept_core}"),
    }[lang]

    out = []
    for i, (K, sub) in enumerate(((full, labels[0]), (reduced, labels[1]))):
        ox = PANEL_INSET + i * (CORE_PANEL_W + 80)
        deg = dict(K.degree())
        lo, hi = 0, max(max(deg.values()), 1)
        nodes = [{
            "id": f"{n}-{i}",
            "label": (d["comp"].get(n, {}).get("name") or n),
            "x": pos[n][0], "y": pos[n][1],
            "r": 3.0 + radius(deg[n], lo, hi) * 0.42,
            "color": p["series"][0] if deg[n] else p["other"],
        } for n in inner]
        edges = [(pos[u], pos[v], attr["weight"])
                 for u, v, attr in sorted(K.edges(data=True),
                                          key=lambda e: (e[0], e[1]))]
        out.append(f'<g transform="translate({ox:.1f},0)">')
        # Heavy edge ink. The left panel has to read as a filled disc, because
        # that is what a complete graph is, and the right one as visibly sparser.
        # At the opacity the 39,000-edge hairball figures use, 2,556 hairlines
        # and 532 both came out as the same pale haze and the one contrast this
        # figure exists for was invisible.
        out.append(draw_network(nodes, edges, CORE_PANEL_W, CORE_PANEL_H, mode,
                                edge_opacity=3.0, node_ring=1.4))
        out.append(
            f'<text x="0" y="{CORE_PANEL_H + 20:.1f}" font-size="12.5" '
            f'font-weight="600" font-family="ui-sans-serif,system-ui,sans-serif" '
            f'fill="{p["text_primary"]}">{esc(sub)}</text>')
        out.append("</g>")

    cap = {
        "fr": (f"Les {len(inner)} firmes du cœur le plus profond (k = {kmax}), "
               f"disposées en cercle. À gauche, telles qu'elles sont dans le "
               f"jeu de données : un graphe complet, chaque firme liée à toutes "
               f"les autres. À droite, les mêmes firmes une fois retirés les "
               f"seuls liens que {HOLDER} produit — il figure au conseil des "
               f"{len(inner)}, et engendre donc à lui seul les "
               f"{_fmt(full.number_of_edges())} liens du cœur. Il en reste "
               f"{_fmt(surv)} ({_p(surv / max(full.number_of_edges(), 1), lang, 0)}), et "
               f"le cœur tombe de k = {kmax} à k = {kept_core}. Octave Homberg a "
               f"réellement présidé un empire financier de cette taille ; la "
               f"leçon n'est pas que la donnée est fausse, c'est que la "
               f"structure la plus profonde du réseau est portée par un seul "
               f"identifiant, et qu'une erreur de résolution sur ce nom la ferait "
               f"disparaître."),
        "en": (f"The {len(inner)} firms of the deepest core (k = {kmax}), laid out "
               f"on a circle. Left, as the dataset has them: a complete graph, "
               f"every firm tied to every other. Right, the same firms with the "
               f"edges only {HOLDER} produces taken out — he sits on all "
               f"{len(inner)} boards and so generates the core's "
               f"{_fmt(full.number_of_edges())} edges by himself. "
               f"{_fmt(surv)} survive ({_p(surv / max(full.number_of_edges(), 1), lang, 0)}), "
               f"and the core falls from k = {kmax} to k = {kept_core}. Octave "
               f"Homberg really did chair a financial empire of about this size; "
               f"the lesson is not that the data is wrong but that the network's "
               f"deepest structure rests on a single identifier, and one "
               f"resolution error on that name would erase it."),
    }[lang]
    title = {"fr": "Le cœur le plus profond, moins un administrateur",
             "en": "The deepest core, minus one director"}[lang]
    isolated = sum(1 for n in inner if not reduced.degree(n))
    legend = [(p["series"][0], {"fr": "encore reliée", "en": "still connected"}[lang]),
              (p["other"], {"fr": f"isolée après retrait ({isolated})",
                            "en": f"isolated once he is removed ({isolated})"}[lang])]
    tbl = ([Hn(lang, "firm"), Hn(lang, "deg_full"), Hn(lang, "deg_cut")],
           [[d["comp"].get(n, {}).get("name") or n, full.degree(n),
             reduced.degree(n)] for n in inner])
    return "".join(out), CORE_PANEL_H + 30, title, legend, cap, tbl


def fig_period_structure(d, mode, lang):
    rows = [r for r in d["per_period"] if r["firms"]]
    names = [PERIOD_LABEL[r["period"]] for r in rows]
    panels = [
        ({"fr": "firmes", "en": "firms"}[lang],
         list(zip(names, [r["firms"] for r in rows])), _fmt),
        ({"fr": "liens d'interlock", "en": "interlock edges"}[lang],
         list(zip(names, [r["edges"] for r in rows])), _fmt),
        ({"fr": "degré moyen", "en": "mean degree"}[lang],
         list(zip(names, [r["mean_degree"] for r in rows])),
         lambda v: f"{v:.1f}".replace(".", "," if lang == "fr" else ".")),
        ({"fr": "composante géante", "en": "giant component"}[lang],
         list(zip(names, [r["giant_share"] * 100 for r in rows])),
         lambda v: f"{v:.0f}%"),
    ]
    body = mini_columns(panels, 1340, 300, mode)
    cap = {
        "fr": ("Quatre mesures de structure, une par panneau, chacune sur sa "
               "propre échelle : les unités diffèrent, et un axe partagé — ou "
               "pire, deux axes verticaux sur un même graphique — rendrait la "
               "comparaison fausse. Chaque tranche est reconstruite à partir des "
               "seuls liens datés de la période, si bien qu'une firme non datée "
               "n'apparaît dans aucune. Comparer deux périodes compare aussi "
               "deux volumes de dépouillement (figures 8 et 9)."),
        "en": ("Four structural measures, one per panel, each on its own scale: "
               "the units differ, and a shared axis — or worse, two vertical "
               "axes on one chart — would make the comparison false. Each slice "
               "is rebuilt from that period's dated edges alone, so an undated "
               "firm appears in none of them. Comparing two periods also "
               "compares two amounts of reading (figures 8 and 9)."),
    }[lang]
    title = {"fr": "Structure du réseau par période",
             "en": "Network structure by period"}[lang]
    tbl = ([Hn(lang, "period"), Hn(lang, "firms"), Hn(lang, "edges"),
            Hn(lang, "mean_deg"), Hn(lang, "giant")],
           [[PERIOD_LABEL[r["period"]], r["firms"], r["edges"],
             f"{r['mean_degree']:.2f}", f"{r['giant_share']:.1%}"] for r in rows])
    return body, 300, title, None, cap, tbl


# --- table headers --------------------------------------------------------
_HEAD = {
    "fr": {"degree": "degré", "share_all": "P(K≥k) tous liens",
           "share_2": "P(K≥k) poids ≥ 2", "k": "k", "firms": "firmes",
           "density": "densité", "community": "communauté",
           "terr_dom": "territoire dominant", "w": "poids minimal",
           "edges": "liens", "giant": "composante géante",
           "distance": "distance", "pairs": "paires", "pct": "%",
           "period": "période", "across": "franchissants", "within": "internes",
           "person": "identifiant", "terr_n": "territoires",
           "firm": "firme", "deg_full": "degré observé",
           "deg_cut": "degré sans lui", "mean_deg": "degré moyen"},
    "en": {"degree": "degree", "share_all": "P(K≥k) all edges",
           "share_2": "P(K≥k) weight ≥ 2", "k": "k", "firms": "firms",
           "density": "density", "community": "community",
           "terr_dom": "dominant territory", "w": "minimum weight",
           "edges": "edges", "giant": "giant component",
           "distance": "distance", "pairs": "pairs", "pct": "%",
           "period": "period", "across": "crossing", "within": "within",
           "person": "identifier", "terr_n": "territories",
           "firm": "firm", "deg_full": "degree observed",
           "deg_cut": "degree without him", "mean_deg": "mean degree"},
}


def Hn(lang: str, key: str) -> str:
    return _HEAD[lang][key]


FIGURES = [
    ("fig18_degree_distribution", fig_degree_distribution, 1040.0),
    ("fig19_kcore_profile", fig_kcore_profile, 1040.0),
    ("fig20_community_backbone", fig_community_backbone, COMM_W),
    ("fig21_giant_vs_threshold", fig_giant_vs_threshold, 1040.0),
    ("fig22_path_lengths", fig_path_lengths, 1040.0),
    ("fig23_community_territory", fig_community_territory, 1040.0),
    ("fig24_cross_territory", fig_cross_territory, 1040.0),
    ("fig25_person_reach", fig_person_reach, 1040.0),
    ("fig26_innermost_core", fig_innermost_core, CORE_PANEL_W * 2 + 80 + PANEL_INSET * 2),
    ("fig27_period_structure", fig_period_structure, 1340.0),
]


# --- the measures file ----------------------------------------------------
def write_measures(d) -> str:
    """The scalars the captions quote, as data rather than as rendered text.

    A number that exists only inside an SVG cannot be cited, checked or
    recomputed. Every figure caption here draws from this file's contents.
    """
    G = d["G"]
    total = sum(d["paths"].values())
    w, a, _u = d["cross_all"]
    kmax = max(d["core"].values())
    rows = [
        ("n_firms", G.number_of_nodes(), "firms in the interlock graph"),
        ("n_interlocks", G.number_of_edges(), "interlock edges, weight >= 1"),
        ("n_components", len(d["comps"]), "connected components"),
        ("giant_share", f"{len(d['giant']) / G.number_of_nodes():.4f}",
         "share of firms in the largest component"),
        ("giant_share_w2", f"{d['thresholds'][1]['share']:.4f}",
         "the same at weight >= 2"),
        ("max_degree", max(d["deg_all"]), "highest degree, weight >= 1"),
        ("max_degree_w2", max(d["deg_2"]), "highest degree, weight >= 2"),
        ("max_core_number", kmax, "deepest k-core"),
        ("max_core_size", len(d["shells"][kmax]), "firms in it"),
        ("max_core_density", f"{d['shell_density'][kmax]:.4f}",
         "1.0 means a complete graph"),
        ("mean_path_length",
         f"{sum(k * v for k, v in d['paths'].items()) / total:.4f}",
         f"sampled from {d['n_sources']} sources, seed {PATH_SEED}"),
        ("longest_path_observed", max(d["paths"]), "in the same sample"),
        ("degree_assortativity", f"{d['assortativity']:.4f}",
         "positive: hubs attach to hubs"),
        ("average_clustering", f"{d['clustering']:.4f}", "mean local clustering"),
        ("transitivity", f"{d['transitivity']:.4f}", "global clustering"),
        ("n_communities", len(d["parts"]), f"Louvain, seed {LOUVAIN_SEED}"),
        ("modularity", f"{d['modularity']:.4f}", "of that partition"),
        ("cross_territory_share", f"{a / max(w + a, 1):.4f}",
         "interlocks joining two territories"),
    ]
    ensure_dir(PROC)
    path = os.path.join(PROC, "network_measures.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["measure", "value", "note"])
        wr.writerows(rows)
    return path


# --- the page -------------------------------------------------------------
def render_page(d, lang: str) -> str:
    from make_descriptive_figures import PAGE_CSS

    title = {"fr": "La forme du réseau, en dix mesures",
             "en": "The shape of the network, in ten measures"}[lang]
    lede = {
        "fr": ("Une composante ou plusieurs, un cœur réel ou un artefact, un "
               "petit monde tenu par quoi. Ce que la topologie du graphe dit "
               "d'elle-même, avant qu'on lui fasse dire quoi que ce soit sur "
               "l'empire."),
        "en": ("One component or several, a real core or an artefact, a small "
               "world held together by what. What the graph's topology says "
               "about itself, before it is made to say anything about the "
               "empire."),
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
    page = os.path.join(out_dir, "structure.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(render_page(d, args.lang))

    # The measures file is language-independent, so it is written once.
    if args.lang == "fr":
        path = write_measures(d)
        print(f"wrote {os.path.relpath(path, ROOT)}", file=sys.stderr)
    print(f"wrote {len(FIGURES)} structural figures + structure.html to "
          f"{os.path.relpath(out_dir, os.path.dirname(FIG_DIR))}", file=sys.stderr)


if __name__ == "__main__":
    main()
