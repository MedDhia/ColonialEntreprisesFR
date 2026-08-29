"""Stage 13 - the node-level figures.

    python3 src/make_node_figures.py --lang en   # -> figures/en/fig28..fig33
    python3 src/make_node_figures.py             # -> figures/

Stages 7, 8 and 10 draw the network at the scale of the whole: 170 firms in a
core, 5,862 in a hairball, 42 territory graphs, a map. Those answer "what does
this look like". None of them answers "which firms, exactly" — at that density
a node is a dot, an edge is one of thirty-nine thousand, and the fourteen
labels that fit live in the margin on leader lines.

Six figures where the unit of reading is the individual node. Every firm drawn
here can be named, every edge can be followed, and the ones that carry a
category say which:

    fig28  the backbone, labelled          which firms hold the core together
    fig29  concentric k-core rings         how the elite is layered
    fig30  arc diagram by territory        which ties cross a colonial border
    fig31  directors and shared boards     how an interlock is actually made
    fig32  six neighbourhoods              what one firm's world looks like
    fig33  the backbone, by head office    is the core colonial or metropolitan

`fig33` deliberately reuses `fig28`'s firms and `fig28`'s coordinates and
changes only the colour, which is the same device as `fig1`/`fig6`: hold
everything but the encoding fixed and the difference between the two pictures
is the finding rather than an artefact of two layouts.

The drawing primitives are in `draw.py`, which explains why they differ from
`make_figures.draw_network` — curved edges, categorical edge colour, in-place
haloed labels and layouts that put a variable on the canvas rather than a
force-directed approximation of one.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import draw  # noqa: E402
from build_network import read_csv  # noqa: E402
from common import ensure_dir  # noqa: E402
from labels import LANGS, localise  # noqa: E402
from make_figures import (  # noqa: E402
    FIG_DIR, PALETTE, esc, normalise, svg_document, trim_to_width,
)
from make_descriptive_figures import PAGE_CSS, _fmt, _table_html  # noqa: E402
from make_network_figures import NON_TERRITORY, louvain  # noqa: E402

# The backbone: firms sharing at least this many directors, then the busiest
# `BACKBONE_N` of them. Three is the point where the graph stops being held up
# by single-name edges (stage 12, fig21) and 70 is the most nodes that can each
# carry a readable label on a 1340px canvas.
BACKBONE_W = 3
BACKBONE_N = 55

# Rings: firms this deep in the k-core hierarchy or deeper.
RING_FLOOR = 25
ARC_N = 56
# Arcs below this many shared directors are not drawn. At weight 1 the eighty
# firms carry 1,070 arcs and the upper half of the figure is a solid wash, in
# which "most of these cross a border" is a colour rather than a reading.
ARC_W = 2
EGO_FIRMS = [
    "Banque de l’Indochine",
    "Compagnie générale des colonies",
    "Société financière française et coloniale",
    "Compagnie du Port de Fedhala",
    "Compagnie Forestière Sangha-Oubangui",
    "Société des Caoutchoucs de l'Indochine",
]
EGO_MAX = 15
TOP_DIRECTORS = 14
SHARED_FLOOR = 3

PLACE_GROUPS = ["metropole", "empire", "foreign"]
PLACE_LABEL = {
    "fr": {"metropole": "France métropolitaine", "empire": "dans l'empire",
           "foreign": "étranger", "": "siège inconnu"},
    "en": {"metropole": "metropolitan France", "empire": "in the empire",
           "foreign": "foreign", "": "head office unknown"},
}

W = 1340.0


# --- data -----------------------------------------------------------------
def _terr(rec: dict) -> str:
    return (rec.get("countries") or rec.get("regions") or "").split("; ")[0]


def _norm(t: str) -> str:
    return t.lower().replace("’", "'").replace("‘", "'")


def gather() -> dict:
    import networkx as nx

    comp = {c["company_id"]: c for c in read_csv("companies.csv")}
    places = {r["company_id"]: r for r in read_csv("company_places.csv")}

    G = nx.Graph()
    for e in read_csv("edges_company_interlock.csv"):
        G.add_edge(e["company_id_1"], e["company_id_2"], weight=int(e["weight"]))

    # Board seats, for the two-mode figure.
    seats: dict[str, set] = defaultdict(set)
    for e in read_csv("edges_person_company.csv"):
        if e["is_board_seat"] == "1":
            seats[e["person_id"]].add(e["company_id"])

    core = nx.core_number(G)
    parts = louvain(G)
    community = {n: i for i, c in enumerate(parts) for n in c}
    return {"comp": comp, "places": places, "G": G, "seats": seats,
            "core": core, "community": community, "n_parts": len(parts)}


def backbone(d):
    """The `BACKBONE_N` busiest firms of the weight >= 3 graph, one component.

    Every set operation here is resolved into a sorted list before it reaches a
    layout: a spring layout assigns its seeded starting coordinates in node
    order, so an unordered node set silently makes the figure irreproducible.
    """
    import networkx as nx

    G = d["G"]
    H = nx.Graph((u, v, a) for u, v, a in G.edges(data=True)
                 if a["weight"] >= BACKBONE_W)
    wdeg = dict(H.degree(weight="weight"))
    keep = sorted(wdeg, key=lambda n: (-wdeg[n], n))[:BACKBONE_N]
    K = nx.Graph()
    K.add_nodes_from(sorted(keep))
    K.add_edges_from((u, v, a) for u, v, a in H.edges(data=True)
                     if u in set(keep) and v in set(keep))
    biggest = max(nx.connected_components(K), key=lambda c: (len(c), min(c)))
    L = nx.Graph()
    L.add_nodes_from(sorted(biggest))
    L.add_edges_from((u, v, a) for u, v, a in K.edges(data=True)
                     if u in biggest and v in biggest)
    pos = nx.spring_layout(L, k=3.1 / math.sqrt(max(L.number_of_nodes(), 1)),
                           iterations=500, seed=17, weight="weight")
    # `robust` fits to a central percentile band instead of the extremes: a
    # spring layout throws one or two nodes far out, and scaling to the true
    # min/max then squeezes everything else into the middle third of the canvas
    # with the labels on top of one another.
    return L, normalise(pos, W, 700.0, pad=46, pad_x=104.0, robust=0.02)


def _top_territories(ids, d, n=3):
    counts = Counter(_terr(d["comp"].get(i, {})) for i in ids)
    counts.pop("", None)
    counts.pop(NON_TERRITORY, None)
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def _terr_colour(t, slot, mode):
    p = PALETTE[mode]
    return p["series"][slot[t]] if t in slot else p["other"]


# --- fig28 / fig33 --------------------------------------------------------
def _backbone_nodes(d, mode, lang, colour, tip):
    L, pos = d["backbone"]
    wdeg = dict(L.degree(weight="weight"))
    hi = max(wdeg.values())
    nodes = []
    for n in sorted(L.nodes()):
        rec = d["comp"].get(n, {})
        nodes.append({
            "id": n,
            "label": trim_to_width(rec.get("name") or n, draw.LABEL_FONT, 190.0),
            "x": pos[n][0], "y": pos[n][1],
            "r": draw.area_radius(wdeg[n], hi, 15.0, 3.4),
            "color": colour(n),
            "tip": tip(n),
            "wdeg": wdeg[n],
        })
    # Biggest first, so the firms a reader most wants named get a label slot.
    nodes.sort(key=lambda n: (-n["r"], n["id"]))
    return L, nodes


def ordered_subgraph(G, nodes):
    """`G.subgraph(nodes)`, but with a node and edge order the caller controls.

    A NetworkX subgraph is a *view* that iterates its filter, and that filter is
    a `set` of node names. Python randomises string hashing per process, so both
    the node order and — because `edges()` reports each edge in adjacency order
    — the *orientation* of every edge pair change from run to run. That was
    enough on its own to make the arc diagram non-reproducible: the arcs land in
    the same places, but the path segments are emitted in a different order and
    the file is not the same file. `make_figures.ordered_subgraph` exists for
    exactly this reason on the other side of the repository.
    """
    import networkx as nx

    keep = list(nodes)
    wanted = set(keep)
    K = nx.Graph()
    K.add_nodes_from(keep)
    K.add_edges_from((u, v, a) for u, v, a in G.edges(data=True)
                     if u in wanted and v in wanted)
    return K


def _cross(d, u, v) -> bool:
    a, b = _terr(d["comp"].get(u, {})), _terr(d["comp"].get(v, {}))
    return bool(a and b and a != b)


def fig_backbone(d, mode, lang):
    p = PALETTE[mode]
    L, _pos = d["backbone"]
    top3 = _top_territories(L.nodes(), d)
    slot = {t: i for i, t in enumerate(top3)}
    terr_word = {"fr": "territoire", "en": "territory"}[lang]
    shared = {"fr": "adm. partagés", "en": "shared directors"}[lang]
    wdeg_all = dict(L.degree(weight="weight"))

    def tip(n):
        rec = d["comp"].get(n, {})
        t = localise(_terr(rec), lang) or "—"
        return (f'{rec.get("name") or n} · {terr_word}: {t} · '
                f'{wdeg_all[n]} {shared}')

    L, nodes = _backbone_nodes(d, mode, lang,
                               lambda n: _terr_colour(_terr(d["comp"].get(n, {})),
                                                      slot, mode), tip)
    at = {n["id"]: (n["x"], n["y"]) for n in nodes}
    edges = [(at[u], at[v], (a["weight"], _cross(d, u, v)))
             for u, v, a in sorted(L.edges(data=True), key=lambda e: (e[0], e[1]))]
    cross_n = sum(1 for _, _, (_w, c) in edges if c)

    # The cross-territory distinction is a step along the neutral ramp, not a
    # hue. The nodes already spend the categorical slots on territory, and the
    # first version painted cross-territory edges in slot 2 — the same orange as
    # the Algeria nodes beside them, so one colour meant two different things in
    # one figure. Hue for the cross/within split belongs in figure 30, where
    # nothing else competes for it.
    # Both greys come from the mark ramp, not the text ramp. The first version
    # used `text_muted` here, which reads correctly and is still wrong: text
    # tokens are for ink a reader reads, mark tokens for ink a reader measures,
    # and `checks.py` now polices the boundary on strokes as well as fills.
    body = draw.curved_edges(
        edges, mode,
        colour_of=lambda pl: p["other"] if pl[1] else p["edge"],
        width_of=lambda pl: min(0.7 + 0.34 * (pl[0] - BACKBONE_W), 3.2)
        * (1.25 if pl[1] else 1.0),
        opacity_of=lambda pl: (0.5 if pl[1] else 0.55),
    )
    body += draw.hoverable(nodes, mode)
    body += "".join(
        draw.halo_text(mode, x, y, n["label"], anchor)
        for n, x, y, anchor in draw.place_labels(nodes, W, 700.0)
    )
    cap = {
        "fr": (f"Les {len(nodes)} firmes les plus liées du graphe à trois "
               f"administrateurs partagés ou plus — le seuil au-delà duquel le "
               f"réseau ne tient plus par des liens à un seul nom (figure 21). "
               f"L'aire d'un nœud est son degré pondéré et sa couleur son "
               f"territoire ; un lien unissant deux territoires différents est "
               f"tracé plus sombre et plus épais — {cross_n} des {len(edges)} "
               f"liens dessinés. La distinction est un pas de gris et non une "
               f"teinte : les teintes sont déjà prises par les territoires, et "
               f"la même couleur ne peut pas dire deux choses dans une figure. "
               f"Les noms qui ne tenaient pas sont dans le tableau."),
        "en": (f"The {len(nodes)} most-connected firms of the graph at three or "
               f"more shared directors — the threshold past which the network is "
               f"no longer held up by single-name edges (figure 21). Node area "
               f"is weighted degree and colour is territory; an edge joining "
               f"two different territories is drawn darker and heavier — "
               f"{cross_n} of the {len(edges)} drawn. That distinction is a step "
               f"along the grey ramp rather than a hue: the hues are already "
               f"spent on territory, and one colour cannot mean two things in "
               f"one figure. Names that would not fit are in the table."),
    }[lang]
    title = {"fr": "L'ossature du réseau, firme par firme",
             "en": "The backbone of the network, firm by firm"}[lang]
    legend = [(p["series"][slot[t]], localise(t, lang)) for t in top3]
    legend.append((p["other"], {"fr": "autre territoire",
                                "en": "other territory"}[lang]))
    legend.append((p["other"], {"fr": f"lien inter-territoires ({cross_n})",
                                "en": f"cross-territory tie ({cross_n})"}[lang]))
    legend.append((p["edge"], {"fr": "lien interne à un territoire",
                               "en": "tie within one territory"}[lang]))
    tbl = ([Hn(lang, "firm"), Hn(lang, "terr"), Hn(lang, "wdeg")],
           [[d["comp"].get(n["id"], {}).get("name") or n["id"],
             localise(_terr(d["comp"].get(n["id"], {})), lang) or "—", n["wdeg"]]
            for n in sorted(nodes, key=lambda n: (-n["wdeg"], n["id"]))])
    return body, 700.0, title, legend, cap, tbl


def fig_backbone_by_place(d, mode, lang):
    p = PALETTE[mode]
    slot = {g: i for i, g in enumerate(PLACE_GROUPS)}

    def group(n):
        return d["places"].get(n, {}).get("group", "")

    def tip(n):
        rec = d["comp"].get(n, {})
        pl = d["places"].get(n, {})
        city = pl.get("city") or PLACE_LABEL[lang][""]
        return f'{rec.get("name") or n} · {city}'

    L, nodes = _backbone_nodes(
        d, mode, lang,
        lambda n: p["series"][slot[group(n)]] if group(n) in slot else p["other"],
        tip)
    at = {n["id"]: (n["x"], n["y"]) for n in nodes}
    edges = [(at[u], at[v], a["weight"])
             for u, v, a in sorted(L.edges(data=True), key=lambda e: (e[0], e[1]))]
    body = draw.curved_edges(
        edges, mode, width_of=lambda w: min(0.7 + 0.34 * (w - BACKBONE_W), 3.2),
        opacity_of=lambda w: 0.42)
    body += draw.hoverable(nodes, mode)
    body += "".join(
        draw.halo_text(mode, x, y, n["label"], anchor)
        for n, x, y, anchor in draw.place_labels(nodes, W, 700.0)
    )
    counts = Counter(group(n["id"]) for n in nodes)
    known = sum(counts[g] for g in PLACE_GROUPS)
    metro = counts["metropole"] / known if known else 0.0
    cap = {
        "fr": (f"Les mêmes firmes et exactement les mêmes coordonnées que la "
               f"figure 28, recolorées selon le lieu du siège social : la "
               f"différence entre les deux images est donc le codage, pas une "
               f"nouvelle disposition. Des {known} firmes de l'ossature dont "
               f"l'adresse est connue, {metro:.0%} étaient dirigées depuis la "
               f"métropole. {counts['']} n'ont pas d'adresse retrouvable et "
               f"restent grises — ce n'est pas une quatrième catégorie."),
        "en": (f"The same firms and exactly the same coordinates as figure 28, "
               f"recoloured by where the head office was: the difference between "
               f"the two pictures is therefore the encoding, not a second "
               f"layout. Of the {known} backbone firms with a recoverable "
               f"address, {metro:.0%} were run from metropolitan France. "
               f"{counts['']} have no recoverable address and stay grey — that "
               f"is not a fourth category."),
    }[lang]
    title = {"fr": "La même ossature, par lieu du siège",
             "en": "The same backbone, by head office"}[lang]
    legend = [(p["series"][slot[g]], PLACE_LABEL[lang][g]) for g in PLACE_GROUPS]
    legend.append((p["other"], PLACE_LABEL[lang][""]))
    tbl = ([Hn(lang, "firm"), Hn(lang, "city"), Hn(lang, "group")],
           [[d["comp"].get(n["id"], {}).get("name") or n["id"],
             d["places"].get(n["id"], {}).get("city") or "—",
             PLACE_LABEL[lang][group(n["id"])]]
            for n in sorted(nodes, key=lambda n: (-n["wdeg"], n["id"]))])
    return body, 700.0, title, legend, cap, tbl


# --- fig29 ----------------------------------------------------------------
RINGS_H = 860.0


def fig_core_rings(d, mode, lang):
    """Every firm at core >= RING_FLOOR, on a ring for its core number.

    A force layout would put the deep core in the middle *approximately*, by
    pulling on it harder than on anything else. Putting it there by
    construction turns an impression into a reading: the ring a firm sits on is
    its core number, so radius is a measured quantity and the picture stops
    being an argument about the layout algorithm.
    """
    p = PALETTE[mode]
    core = d["core"]
    ks = sorted({k for k in core.values() if k >= RING_FLOOR})
    members = {k: sorted(n for n, v in core.items() if v == k) for k in ks}
    # Angle by community, so a community occupies a sector of every ring it
    # reaches and the rings can be compared to one another.
    for k in ks:
        members[k].sort(key=lambda n: (d["community"].get(n, 10 ** 6), n))

    cx, cy = W / 2, RINGS_H / 2
    r_in, r_out = 74.0, min(cx, cy) - 46.0
    radii = {k: r_out - (r_out - r_in) * i / max(len(ks) - 1, 1)
             for i, k in enumerate(ks)}
    pos = draw.ring_layout([(k, members[k]) for k in ks], cx, cy, radii)

    top3 = _top_territories([n for k in ks for n in members[k]], d)
    slot = {t: i for i, t in enumerate(top3)}
    terr_word = {"fr": "territoire", "en": "territory"}[lang]
    nodes = []
    for k in ks:
        for n in members[k]:
            rec = d["comp"].get(n, {})
            nodes.append({
                "id": n, "label": "",
                "x": pos[n][0], "y": pos[n][1],
                "r": 2.4 + 2.6 * (k == ks[-1]),
                "color": _terr_colour(_terr(rec), slot, mode),
                "tip": f'{rec.get("name") or n} · k = {k} · {terr_word}: '
                       f'{localise(_terr(rec), lang) or "—"}',
            })

    body = []
    # Ring guides first, hairline and behind everything.
    for k in ks:
        body.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radii[k]:.1f}" '
                    f'fill="none" stroke="{p["hairline"]}" stroke-width="1"/>')
    body.append(draw.hoverable(nodes, mode, ring=1.2))
    # Label a ring every few steps, on the vertical, where no node sits at the
    # top of the ring by construction (the first member is placed at -90 deg,
    # so the label goes just above it and outside).
    for i, k in enumerate(ks):
        if i % 3 and k != ks[0] and k != ks[-1]:
            continue
        # The innermost ring's label goes in the hole at the centre. Above the
        # ring it sat on top of the 72 nodes it names, which are the densest
        # marks in the figure.
        ly = cy if k == ks[-1] else cy - radii[k] - 9
        body.append(draw.halo_text(mode, cx, ly, f"k = {k}", "middle",
                                   font=11.0 if k == ks[-1] else 10.0,
                                   weight="600" if k == ks[-1] else "400",
                                   fill=p["text_secondary"]))
    inner = members[ks[-1]]
    cap = {
        "fr": (f"Les {_fmt(sum(len(members[k]) for k in ks))} firmes dont le "
               f"numéro de cœur atteint {RING_FLOOR} : un anneau par niveau, le "
               f"plus profond au centre. Le rayon est donc une quantité mesurée "
               f"et non le résultat d'un algorithme de placement. La position "
               f"angulaire suit la communauté, si bien qu'une communauté occupe "
               f"un secteur de chaque anneau qu'elle atteint. L'anneau central "
               f"(k = {ks[-1]}, {len(inner)} firmes) est le graphe complet que la "
               f"figure 26 démonte : il est au centre parce qu'un seul "
               f"administrateur l'y met. Les anneaux sont espacés par niveau "
               f"occupé et non proportionnellement à k, si bien que les 24 "
               f"niveaux vides entre 46 et {ks[-1]} n'apparaissent ici que comme "
               f"un intervalle parmi d'autres ; la figure 19 les montre."),
        "en": (f"The {_fmt(sum(len(members[k]) for k in ks))} firms whose core "
               f"number reaches {RING_FLOOR}: one ring per level, deepest at the "
               f"centre. Radius is therefore a measured quantity rather than the "
               f"output of a placement algorithm. Angle follows community, so a "
               f"community occupies a sector of every ring it reaches. The "
               f"innermost ring (k = {ks[-1]}, {len(inner)} firms) is the complete "
               f"graph figure 26 takes apart: it is at the centre because one "
               f"director puts it there. Rings are spaced one per occupied "
               f"level rather than in proportion to k, so the 24 empty levels "
               f"between 46 and {ks[-1]} show here as one gap among many; "
               f"figure 19 shows them as they are."),
    }[lang]
    title = {"fr": f"Les couches du cœur (k ≥ {RING_FLOOR})",
             "en": f"The layers of the core (k ≥ {RING_FLOOR})"}[lang]
    legend = [(p["series"][slot[t]], localise(t, lang)) for t in top3]
    legend.append((p["other"], {"fr": "autre territoire",
                                "en": "other territory"}[lang]))
    tbl = ([Hn(lang, "k"), Hn(lang, "firms"), Hn(lang, "example")],
           [[k, len(members[k]),
             "; ".join((d["comp"].get(n, {}).get("name") or n)[:34]
                       for n in members[k][:2])] for k in reversed(ks)])
    return "".join(body), RINGS_H, title, legend, cap, tbl


# --- fig30 ----------------------------------------------------------------
ARC_H = 620.0


def fig_arc_territory(d, mode, lang):
    """An arc diagram, because the node ordering is itself the variable."""
    p = PALETTE[mode]
    G = d["G"]
    deg = dict(G.degree(weight="weight"))
    pick = sorted(deg, key=lambda n: (-deg[n], n))[:ARC_N]
    # Order along the axis by territory, then by degree inside it. A force
    # layout would order by connection and destroy exactly the variable the
    # figure is about.
    def key(n):
        t = _terr(d["comp"].get(n, {}))
        return (t == "", t == NON_TERRITORY, t, -deg[n], n)

    ordered = sorted(pick, key=key)
    baseline = ARC_H - 218.0
    # The rotated names run down and to the right of their node, so the axis
    # stops short of the canvas edge: run to the full width and the last few
    # firms lose their names off the side.
    pos = draw.line_layout(ordered, 26.0, W - 96.0, baseline)
    sub = ordered_subgraph(G, sorted(ordered))
    pairs = []
    for u, v, a in sorted(sub.edges(data=True),
                          key=lambda e: (min(e[0], e[1]), max(e[0], e[1]))):
        if a["weight"] >= ARC_W:
            pairs.append((pos[u][0], pos[v][0], (a["weight"], _cross(d, u, v))))
    total_arcs = sub.number_of_edges()
    cross_n = sum(1 for _, _, (_w, c) in pairs if c)

    body = [draw.arcs(
        pairs, mode, baseline, baseline - 16.0,
        colour_of=lambda pl: p["series"][1] if pl[1] else p["series"][0],
        width_of=lambda pl: min(0.6 + 0.22 * pl[0], 2.6),
        opacity_of=lambda pl: 0.30 if pl[1] else 0.36,
    )]
    hi = max(deg[n] for n in ordered)
    nodes = [{
        "id": n, "label": "",
        "x": pos[n][0], "y": baseline,
        "r": draw.area_radius(deg[n], hi, 7.0, 2.4),
        # Neutral by design: in this figure the arcs carry the category and the
        # nodes carry none, so they take the mark ramp's grey.
        "color": p["other"],
        "tip": f'{d["comp"].get(n, {}).get("name") or n} · '
               f'{localise(_terr(d["comp"].get(n, {})), lang) or "—"}',
    } for n in ordered]
    body.append(draw.hoverable(nodes, mode, ring=1.2))
    # Names below the axis, rotated, so eighty of them fit side by side.
    for n in ordered:
        x = pos[n][0]
        name = trim_to_width(d["comp"].get(n, {}).get("name") or n, 8.5, 132.0)
        body.append(
            f'<g transform="translate({x:.1f},{baseline + 12:.1f}) rotate(60)">'
            f'{draw.halo_text(mode, 0, 0, name, "start", font=8.5, fill=p["text_secondary"])}'
            f'</g>')
    # Territory brackets under the rotated names, not between them: at
    # baseline + 60 the bracket labels landed in the middle of the firm names
    # and both became unreadable.
    runs = []
    for n in ordered:
        t = _terr(d["comp"].get(n, {}))
        if runs and runs[-1][0] == t:
            runs[-1][2] = pos[n][0]
        else:
            runs.append([t, pos[n][0], pos[n][0]])
    for t, x0, x1 in runs:
        if x1 - x0 < 46:
            continue
        label = localise(t, lang) if t else {"fr": "non renseigné",
                                             "en": "unrecorded"}[lang]
        by = baseline + 150.0
        body.append(f'<line x1="{x0:.1f}" y1="{by:.1f}" '
                    f'x2="{x1:.1f}" y2="{by:.1f}" '
                    f'stroke="{p["hairline"]}" stroke-width="2"/>')
        body.append(draw.halo_text(mode, (x0 + x1) / 2, by + 15,
                                   trim_to_width(label, 11.0, x1 - x0),
                                   "middle", font=11.0,
                                   fill=p["text_secondary"]))
    cap = {
        "fr": (f"Les {len(ordered)} firmes de plus fort degré pondéré, rangées "
               f"le long de l'axe par territoire puis par degré. Chaque arc est "
               f"un lien reposant sur au moins {ARC_W} administrateurs partagés "
               f"— {_fmt(len(pairs))} des {_fmt(total_arcs)} liens entre ces "
               f"firmes ; à un seul administrateur la moitié supérieure du "
               f"graphique devient un aplat. "
               f"{cross_n} de ces {len(pairs)} arcs "
               f"({cross_n / max(len(pairs), 1):.0%}) franchissent une "
               f"frontière : c'est la figure 24 vue firme par firme. Un "
               f"diagramme en arcs sacrifie la disposition en deux dimensions "
               f"pour garder un ordre lisible ; ici l'ordre est la variable, "
               f"donc c'est le bon échange."),
        "en": (f"The {len(ordered)} firms of highest weighted degree, ranged "
               f"along the axis by territory and then by degree. Each arc is a "
               f"tie resting on at least {ARC_W} shared directors — "
               f"{_fmt(len(pairs))} of the {_fmt(total_arcs)} ties among these "
               f"firms; at one shared director the upper half of the figure "
               f"becomes a solid wash. "
               f"{cross_n} of those {len(pairs)} arcs "
               f"({cross_n / max(len(pairs), 1):.0%}) cross a border: this is "
               f"figure 24 seen firm by firm. An arc diagram gives up the "
               f"two-dimensional layout to keep a readable ordering; here the "
               f"ordering is the variable, so that is the right trade."),
    }[lang]
    title = {"fr": "Qui est lié à qui, par territoire",
             "en": "Who is tied to whom, by territory"}[lang]
    legend = [(p["series"][0], {"fr": "lien interne à un territoire",
                                "en": "tie within one territory"}[lang]),
              (p["series"][1], {"fr": "lien inter-territoires",
                                "en": "tie across territories"}[lang])]
    tbl = ([Hn(lang, "firm"), Hn(lang, "terr"), Hn(lang, "wdeg")],
           [[d["comp"].get(n, {}).get("name") or n,
             localise(_terr(d["comp"].get(n, {})), lang) or "—", deg[n]]
            for n in ordered])
    return "".join(body), ARC_H, title, legend, cap, tbl


# --- fig31 ----------------------------------------------------------------
TWO_MODE_H = 900.0


def _barycentre(left, right, adj_l, adj_r, passes=8):
    """Order both sides of a bipartite drawing to cut edge crossings.

    The standard heuristic: repeatedly place each node at the average position
    of its neighbours on the other side. Ordered by seat count, this figure's
    edges made a solid X and no individual directorship could be followed.
    Ties break on the identifier, so the result is a function of the data.
    """
    for _ in range(passes):
        rank_r = {c: i for i, c in enumerate(right)}
        left.sort(key=lambda x: (sum(rank_r[c] for c in adj_l[x])
                                 / max(len(adj_l[x]), 1), x))
        rank_l = {x: i for i, x in enumerate(left)}
        right.sort(key=lambda c: (sum(rank_l[x] for x in adj_r[c])
                                  / max(len(adj_r[c]), 1), c))
    return left, right


def fig_shared_boards(d, mode, lang):
    """The two-mode graph the repository projects from but never draws."""
    p = PALETTE[mode]
    seats = d["seats"]
    people = sorted(seats, key=lambda x: (-len(seats[x]), x))[:TOP_DIRECTORS]
    counts = Counter()
    for person in people:
        for c in sorted(seats[person]):
            counts[c] += 1
    firms = sorted((c for c, n in counts.items() if n >= SHARED_FLOOR),
                   key=lambda c: (-counts[c], c))
    adj_l = {x: sorted(c for c in firms if c in seats[x]) for x in people}
    adj_r = {c: sorted(x for x in people if c in seats[x]) for c in firms}
    people, firms = _barycentre(people, firms, adj_l, adj_r)

    pos = draw.column_layout(people, firms, 330.0, W - 380.0, 40.0,
                             TWO_MODE_H - 40.0)
    edges = [(pos[x], pos[c], counts[c])
             for x in sorted(people) for c in adj_l[x]]
    body = [draw.curved_edges(edges, mode, bow=0.03,
                              colour_of=lambda w: p["other"],
                              opacity_of=lambda w: 0.45, width_of=lambda w: 1.0)]

    hi_p = max(len(seats[x]) for x in people)
    hi_c = max(counts[c] for c in firms) if firms else 1
    person_nodes = [{
        "id": x, "label": x, "x": pos[x][0], "y": pos[x][1],
        "r": draw.area_radius(len(seats[x]), hi_p, 13.0, 4.0),
        "color": p["series"][0],
        "tip": f'{x} · {len(seats[x])} '
               + {"fr": "sièges", "en": "seats"}[lang],
    } for x in people]
    firm_nodes = [{
        "id": c, "label": trim_to_width(d["comp"].get(c, {}).get("name") or c,
                                        draw.LABEL_FONT, 236.0),
        "x": pos[c][0], "y": pos[c][1],
        "r": draw.area_radius(counts[c], hi_c, 9.0, 3.2),
        "color": p["series"][2],
        "tip": f'{d["comp"].get(c, {}).get("name") or c} · {counts[c]} '
               + {"fr": "de ces administrateurs",
                  "en": "of these directors"}[lang],
    } for c in firms]
    body.append(draw.hoverable(person_nodes + firm_nodes, mode))
    for n in person_nodes:
        body.append(draw.halo_text(mode, n["x"] - n["r"] - 7, n["y"] + 3.6,
                                   n["label"], "end"))
    for n in firm_nodes:
        body.append(draw.halo_text(mode, n["x"] + n["r"] + 7, n["y"] + 3.6,
                                   n["label"], "start"))

    junk = [x for x in people if "-" not in x]
    cap = {
        "fr": (f"À gauche les {len(people)} personnes détenant le plus de "
               f"sièges, à droite les {len(firms)} firmes sur lesquelles au "
               f"moins {SHARED_FLOOR} d'entre elles siègent — c'est-à-dire la "
               f"matière première des interlocks, avant projection. Chaque arête "
               f"est un mandat observé, pas une inférence : le graphe une-mode "
               f"que dessine tout le reste du dépôt se fabrique en reliant deux "
               f"firmes chaque fois qu'un point de gauche les touche toutes les "
               f"deux. C'est aussi pourquoi une seule personne mal résolue "
               f"déplace beaucoup d'arêtes. Les deux colonnes sont ordonnées "
               f"pour minimiser les croisements et non par un regroupement "
               f"imposé ici : que les firmes indochinoises se retrouvent en "
               f"haut et les marocaines en bas est un résultat de cet ordre, "
               f"pas une donnée d'entrée. "
               + ("Les identifiants sans initiale — "
                  + ", ".join(f"« {x} »" for x in junk)
                  + " — sont des noms de famille seuls que la résolution n'a pas "
                  "pu rattacher, et non des personnes ; ils restent visibles."
                  if junk else "")),
        "en": (f"On the left the {len(people)} people holding the most board "
               f"seats, on the right the {len(firms)} firms that at least "
               f"{SHARED_FLOOR} of them sit on — the raw material of every "
               f"interlock, before projection. Each edge is one observed "
               f"directorship rather than an inference: the one-mode graph the "
               f"rest of this repository draws is made by joining two firms "
               f"whenever a point on the left touches both. It is also why one "
               f"badly resolved person moves a great many edges. Both columns "
               f"are ordered to minimise edge crossings, not by any grouping "
               f"imposed here; that the Indochina firms end up together at the "
               f"top and the Moroccan ones at the bottom is a result of the "
               f"ordering rather than an input to it. "
               + ("The identifiers with no initial — "
                  + ", ".join(f"“{x}”" for x in junk)
                  + " — are bare surnames resolution could not attach rather "
                  "than people; they stay visible."
                  if junk else "")),
    }[lang]
    title = {"fr": "Comment se fabrique un interlock",
             "en": "How an interlock is actually made"}[lang]
    legend = [(p["series"][0], {"fr": "administrateur", "en": "director"}[lang]),
              (p["series"][2], {"fr": "firme", "en": "firm"}[lang])]
    tbl = ([Hn(lang, "firm"), Hn(lang, "n_directors")],
           [[d["comp"].get(c, {}).get("name") or c, counts[c]] for c in firms])
    return "".join(body), TWO_MODE_H, title, legend, cap, tbl


# --- fig32 ----------------------------------------------------------------
EGO_W, EGO_H = 430.0, 330.0
EGO_ROWS, EGO_COLS = 2, 3
EGOS_H = EGO_ROWS * (EGO_H + 54.0)


def fig_ego_multiples(d, mode, lang):
    """Six neighbourhoods, each small enough to read every node in it."""
    import networkx as nx

    p = PALETTE[mode]
    G = d["G"]
    by_name = {}
    for cid, rec in sorted(d["comp"].items()):
        by_name.setdefault(_norm(rec.get("name") or ""), cid)

    body, panels = [], []
    for i, wanted in enumerate(EGO_FIRMS):
        target = None
        want = _norm(wanted)
        for name, cid in by_name.items():
            if want in name and cid in G:
                if target is None or G.degree(cid) > G.degree(target):
                    target = cid
        if target is None:
            continue
        nbrs = sorted(G[target], key=lambda n: (-G[target][n]["weight"], n))
        keep = [target] + nbrs[:EGO_MAX]
        E = nx.Graph()
        E.add_nodes_from(keep)
        E.add_edges_from((u, v, a) for u, v, a in G.edges(data=True)
                         if u in set(keep) and v in set(keep))
        pos = normalise(
            nx.spring_layout(E, k=2.0 / math.sqrt(len(keep)), iterations=340,
                             seed=23 + i, weight="weight"),
            EGO_W, EGO_H, pad=30, pad_x=64.0)
        ox = (i % EGO_COLS) * (EGO_W + 22)
        oy = (i // EGO_COLS) * (EGO_H + 54)
        hi = max(dict(E.degree(weight="weight")).values())
        # The centre's own name is the panel title, so it does not spend a
        # label slot: in-place labels are a scarce resource here and the slot
        # goes to a firm the reader cannot otherwise identify.
        nodes = [{
            "id": f"{n}-{i}",
            "label": "" if n == target else trim_to_width(
                d["comp"].get(n, {}).get("name") or n, 9.0, 118.0),
            "x": pos[n][0], "y": pos[n][1],
            "r": draw.area_radius(E.degree(n, weight="weight"), hi,
                                  11.0 if n == target else 8.0, 2.8),
            "color": p["series"][0] if n == target else p["other"],
            "tip": d["comp"].get(n, {}).get("name") or n,
        } for n in keep]
        at = {f"{n}-{i}": pos[n] for n in keep}
        edges = [(at[f"{u}-{i}"], at[f"{v}-{i}"], a["weight"])
                 for u, v, a in sorted(E.edges(data=True), key=lambda e: (e[0], e[1]))]
        panel = [
            f'<g transform="translate({ox:.1f},{oy:.1f})">',
            draw.curved_edges(edges, mode,
                              width_of=lambda w: min(0.6 + 0.2 * w, 2.4),
                              opacity_of=lambda w: 0.4),
            draw.hoverable(nodes, mode, ring=1.5),
        ]
        panel += [draw.halo_text(mode, x, y, n["label"], anchor, font=9.0)
                  for n, x, y, anchor in
                  draw.place_labels(nodes, EGO_W, EGO_H, font=9.0)]
        name = d["comp"].get(target, {}).get("name") or target
        panel.append(draw.halo_text(mode, 0, EGO_H + 18,
                                    trim_to_width(name, 12.0, EGO_W - 10.0),
                                    "start", font=12.0, weight="600"))
        panel.append(draw.halo_text(
            mode, 0, EGO_H + 34,
            {"fr": f"{G.degree(target)} firmes liées, {len(keep) - 1} dessinées",
             "en": f"{G.degree(target)} firms tied, {len(keep) - 1} drawn"}[lang],
            "start", font=10.5, fill=p["text_secondary"]))
        panel.append("</g>")
        body.append("".join(panel))
        panels.append((name, G.degree(target), len(keep) - 1))

    cap = {
        "fr": ("Six voisinages, chacun réduit aux "
               f"{EGO_MAX} liens les plus lourds de la firme centrale pour que "
               "chaque nœud reste nommable ; la firme centrale est nommée par le "
               "titre du panneau. Ce sont des vues locales : un voisinage petit "
               "ne veut pas dire une firme périphérique, il veut dire que le "
               "reste est coupé, et la ligne sous chaque panneau indique "
               "combien. Deux nœuds distincts portent ici le nom « Banque de "
               "l'Indochine » : c'est la dette de doublons de sociétés que "
               "signale le codebook, laissée visible plutôt que corrigée à la "
               "main dans une figure."),
        "en": ("Six neighbourhoods, each cut to the "
               f"{EGO_MAX} heaviest ties of its centre firm so that every node "
               "stays nameable; the centre firm is named by the panel title. "
               "These are local views: a small neighbourhood does not mean a "
               "peripheral firm, it means the rest is cut away, and the line "
               "under each panel says how much. Two distinct nodes here carry "
               "the name “Banque de l’Indochine”: that is the company-duplicate "
               "debt the codebook flags, left visible rather than hand-corrected "
               "inside a figure."),
    }[lang]
    title = {"fr": "Six voisinages, nœud par nœud",
             "en": "Six neighbourhoods, node by node"}[lang]
    legend = [(p["series"][0], {"fr": "firme centrale", "en": "centre firm"}[lang]),
              (p["other"], {"fr": "firme liée", "en": "tied firm"}[lang])]
    tbl = ([Hn(lang, "firm"), Hn(lang, "degree"), Hn(lang, "drawn")],
           [[n, deg, drawn] for n, deg, drawn in panels])
    return "".join(body), EGOS_H, title, legend, cap, tbl


# --- table headers --------------------------------------------------------
_HEAD = {
    "fr": {"firm": "firme", "terr": "territoire", "wdeg": "degré pondéré",
           "city": "ville", "group": "siège", "k": "k", "firms": "firmes",
           "example": "exemples", "n_directors": "de ces administrateurs",
           "degree": "firmes liées", "drawn": "dessinées"},
    "en": {"firm": "firm", "terr": "territory", "wdeg": "weighted degree",
           "city": "city", "group": "head office", "k": "k", "firms": "firms",
           "example": "examples", "n_directors": "of these directors",
           "degree": "firms tied", "drawn": "drawn"},
}


def Hn(lang: str, key: str) -> str:
    return _HEAD[lang][key]


FIGURES = [
    ("fig28_backbone", fig_backbone),
    ("fig29_core_rings", fig_core_rings),
    ("fig30_arc_territory", fig_arc_territory),
    ("fig31_shared_boards", fig_shared_boards),
    ("fig32_neighbourhoods", fig_ego_multiples),
    ("fig33_backbone_by_place", fig_backbone_by_place),
]


# --- the page -------------------------------------------------------------
def render_page(d, lang: str) -> str:
    title = {"fr": "Le réseau, nœud par nœud",
             "en": "The network, node by node"}[lang]
    lede = {
        "fr": ("Les autres pages montrent la forme de l'ensemble. Celle-ci "
               "montre des graphes assez petits pour qu'on puisse nommer chaque "
               "firme, suivre chaque lien, et voir de quoi le réseau est fait."),
        "en": ("The other pages show the shape of the whole. This one shows "
               "graphs small enough to name every firm, follow every edge, and "
               "see what the network is made of."),
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
        svg = svg_document(body, W, height, "vars", ftitle, legend=legend,
                           caption="")
        out.append(
            f'<figure id="{name}"><h2 style="font-size:16px;margin:0 0 2px">'
            f'{esc(ftitle)}</h2><figcaption>{esc(caption)}</figcaption>{svg}'
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

    d = gather()
    d["backbone"] = backbone(d)
    for name, fn in FIGURES:
        body, height, title, legend, caption, _ = fn(d, "light", args.lang)
        svg = svg_document(body, W, height, "light", title, legend=legend,
                           caption=caption)
        with open(os.path.join(out_dir, f"{name}.svg"), "w", encoding="utf-8") as fh:
            fh.write(svg)
    page = os.path.join(out_dir, "nodes.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(render_page(d, args.lang))
    print(f"wrote {len(FIGURES)} node-level figures + nodes.html to "
          f"{os.path.relpath(out_dir, os.path.dirname(FIG_DIR))}", file=sys.stderr)


if __name__ == "__main__":
    main()
