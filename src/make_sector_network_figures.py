"""Stage 19 - which sector is central, in four network pictures.

    python3 src/make_sector_network_figures.py
    python3 src/make_sector_network_figures.py --lang en

The measures are in `sector_centrality.csv` (stage 18) and the answer is
banking and finance, on every measure that survives a size control. These are
the node-link figures for it, and each is built to show one thing the tables
cannot:

- **fig47, the sector graph.** The 16 sectors as nodes and the interlocks
  between them as edges — the whole cross-sector structure in one picture.
  Node area is the sector's share of network betweenness; the ring is ordered
  by it. Colour separates hubs from brokers, which is the distinction the raw
  ranking hides.
- **fig48, the core, one sector at a time.** The repository's own 170-firm core
  (figure 1's graph and figure 1's coordinates), four panels, one sector lit in
  each. Finance holds 48 of the 170; mining, the sector closest to it in size
  across the whole graph, holds 16.
- **fig49, what removal costs.** The same core at the same coordinates, three
  panels: whole, finance removed, and a size-matched random removal. The edges
  lost stay on the canvas as ghosts, because the point is how much edge mass
  goes with the sector and a blank space cannot show that. Inside the core the
  result inverts — a random draw of the same size costs slightly more — because
  the core is the 170 firms of highest weighted degree, so a random draw inside
  it is a draw of hubs. The z-score's null is drawn from the whole graph.
- **fig50, a hub is not a broker.** Six ego networks: three finance firms with
  the highest betweenness, three firms with the highest `broker_gap`. A hub is a
  star whose neighbours already know each other; a broker is a bridge between
  neighbours who do not. They look nothing alike.

**Every panel that compares two things uses one layout.** Re-running a spring
layout per panel makes two identical graphs look different, and two different
graphs look similar; fig48, fig49 and the comparison in fig50 all place a node
at the same coordinates in every panel it appears in.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


import draw  # noqa: E402
import sectors as S  # noqa: E402
from common import ensure_dir  # noqa: E402
from labels import LANGS  # noqa: E402
from make_descriptive_figures import PAGE_CSS, _axis_text, _table_html  # noqa: E402
from make_figures import (PALETTE, FIG_DIR, build_interlock_graph,  # noqa: E402
                          core_subgraph, esc, layout, normalise,
                          ordered_subgraph, svg_document, trim_to_width)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")

W = 1340.0
AXIS_FONT = 10.5
CORE_TOP = 170          # figure 1's core, so the two figures are comparable
CORE_MIN_WEIGHT = 2
RING_PAIRS = 60         # cross-sector pairs drawn in fig47
EGO_MAX = 22            # neighbours drawn per ego panel
REMOVAL_SEED = 29


def load(name):
    path = os.path.join(PROC, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def gather() -> dict:
    mapping = S.load_map()
    firms = {r["company_id"]: r for r in load("companies.csv")}
    sec_of = {cid: S.sector_of(dict(r, company_id=cid), mapping)[0]
              for cid, r in firms.items()}
    G = build_interlock_graph(CORE_MIN_WEIGHT)
    K = core_subgraph(G, CORE_TOP)
    pos = normalise(layout(K), W, 620.0, pad=40, pad_x=150.0)
    cent = {r["company_id"]: r for r in load("company_centrality.csv")}
    return {
        "firms": firms, "sec_of": sec_of, "core": K, "pos": pos,
        "cent": cent,
        "sector": load("sector_centrality.csv"),
        "pairs": load("edges_sector_interlock.csv"),
        "baseline": (load("sector_centrality_baseline.csv") or [{}])[0],
        "full": build_interlock_graph(1),
    }


def _en(d, group):
    for r in d["sector"]:
        if r["sector_group"] == group:
            return r["sector_group_en"]
    return group


# --- fig47: the sector graph ---------------------------------------------
def fig_sector_graph(d, mode, lang):
    p = PALETTE[mode]
    rows = [r for r in d["sector"] if r["sector_group"] != "not_a_sector"]
    if not rows or not d["pairs"]:
        return "", 40.0, "", None, "", None
    rows.sort(key=lambda r: -float(r["sum_betweenness"]))
    order = [r["sector_group"] for r in rows]
    by = {r["sector_group"]: r for r in rows}

    cx, cy, radius = W / 2, 352.0, 262.0
    ring = draw.ring_layout([(0, order)], cx, cy, [radius])
    # Stretched to an ellipse: a circle of this radius leaves a third of a
    # 1340px canvas empty, and the ordering the ring encodes is unaffected.
    pos = {k: (cx + (x - cx) * 1.48, y) for k, (x, y) in ring.items()}

    hi = max(float(r["sum_betweenness"]) for r in rows) or 1.0
    nodes = []
    for g in order:
        r = by[g]
        gap = float(r["mean_broker_gap"] or 0)
        x, y = pos[g]
        nodes.append({
            "id": g, "x": x, "y": y,
            "r": draw.area_radius(float(r["sum_betweenness"]), hi, 26.0, 4.0),
            # Two slots, and the distinction is the finding: a sector whose
            # firms rank higher on degree than on betweenness is a hub, one
            # where it runs the other way is a broker.
            "color": p["series"][0] if gap < 0 else p["series"][1],
            "label": r["sector_group_en"],
            "tip": (f"{r['sector_group_en']}: {int(r['n_firms']):,} firms, "
                    f"{float(r['edge_share']):.1%} of edges, betweenness "
                    f"{float(r['sum_betweenness']):.4f}, mean broker gap "
                    f"{gap:+.0f}"),
        })
    by_id = {n["id"]: n for n in nodes}
    pairs = [r for r in d["pairs"]
             if r["sector_a"] in by_id and r["sector_b"] in by_id]
    pairs.sort(key=lambda r: -int(r["n_interlocks"]))
    pairs = pairs[:RING_PAIRS]
    hi_e = max(int(r["n_interlocks"]) for r in pairs) or 1
    segs = [((by_id[r["sector_a"]]["x"], by_id[r["sector_a"]]["y"]),
             (by_id[r["sector_b"]]["x"], by_id[r["sector_b"]]["y"]),
             int(r["n_interlocks"])) for r in pairs]
    body = [draw.curved_edges(
        segs, mode, bow=0.20,
        width_of=lambda n: 0.8 + 5.0 * (n / hi_e) ** 0.65,
        opacity_of=lambda n: 0.22 + 0.42 * (n / hi_e) ** 0.5,
        colour_of=lambda n: p["edge"])]
    body.append(draw.hoverable(nodes, mode))
    # Labelled radially, not by `place_labels`. The greedy collision pass is
    # for scattered layouts; on a ring the natural direction is outward from
    # the centre, it never collides for sixteen nodes, and the greedy version
    # was silently dropping four of them — including the third-largest.
    for n in nodes:
        out_x = n["x"] >= cx
        lx = n["x"] + (n["r"] + 7 if out_x else -(n["r"] + 7))
        avail = (W - lx - 6) if out_x else (lx - 6)
        body.append(draw.halo_text(
            mode, lx, n["y"] + 3.6,
            trim_to_width(n["label"], 10.5, max(avail, 40.0)),
            "start" if out_x else "end"))

    fin = by.get("finance", {})
    title = {"fr": "fig. 47 — Le graphe des secteurs",
             "en": "fig. 47 — The sector graph"}[lang]
    caption = {
        "fr": (f"Les {len(order)} secteurs, reliés par les interlocks entre "
               f"leurs firmes ; les {len(pairs)} paires les plus fortes sont "
               f"tracées. L'aire du nœud est la part de bétweenness du réseau, "
               f"et l'anneau est ordonné par elle : la finance vient en tête "
               f"avec {float(fin.get('edge_share', 0)):.0%} de toutes les "
               f"arêtes. La couleur sépare les moyeux des courtiers — un "
               f"secteur dont les firmes se classent plus haut en degré qu'en "
               f"bétweenness est un moyeu — et c'est la distinction que le "
               f"classement brut masque. La finance est un moyeu ; les cinq "
               f"courtiers sont le commerce, le bois, le textile, "
               f"l'hôtellerie et la santé-enseignement, tous petits."),
        "en": (f"The {len(order)} sectors, joined by the interlocks between "
               f"their firms; the {len(pairs)} strongest pairs are drawn. Node "
               f"area is the sector's share of network betweenness and the ring "
               f"is ordered by it: finance leads, touching "
               f"{float(fin.get('edge_share', 0)):.0%} of all edges. Colour "
               f"separates hubs from brokers — a sector whose firms rank higher "
               f"on degree than on betweenness is a hub — which is the "
               f"distinction the raw ranking hides. Finance is a hub; the five "
               f"brokers are trade, wood, textiles, hotels and "
               f"health-and-education, all of them small."),
    }[lang]
    legend = [(p["series"][0], {"fr": "moyeu (degré > bétweenness)",
                               "en": "hub (degree > betweenness)"}[lang]),
              (p["series"][1], {"fr": "courtier (bétweenness > degré)",
                                "en": "broker (betweenness > degree)"}[lang])]
    table = ([{"fr": "Secteur", "en": "Sector"}[lang],
              {"fr": "Firmes", "en": "Firms"}[lang],
              {"fr": "Part des arêtes", "en": "Edge share"}[lang],
              {"fr": "Bétweenness", "en": "Betweenness"}[lang],
              {"fr": "Écart courtier", "en": "Broker gap"}[lang]],
             [(r["sector_group_en"], r["n_firms"],
               f"{float(r['edge_share']):.1%}",
               f"{float(r['sum_betweenness']):.4f}",
               r["mean_broker_gap"]) for r in rows])
    return "".join(body), 704.0, title, legend, caption, table


# --- fig48: the core, one sector at a time -------------------------------
SPOTLIGHT = ["finance", "mining", "transport", "plantations"]


def fig_core_spotlight(d, mode, lang):
    p = PALETTE[mode]
    K, pos, sec_of = d["core"], d["pos"], d["sec_of"]
    if not K.number_of_nodes():
        return "", 40.0, "", None, "", None
    cols, pw, ph, gap = 2, W / 2 - 12, 236.0, 16.0
    # One layout for every panel: the same firm sits at the same point in all
    # four, which is what makes the four readable as one comparison.
    xs = [pos[n][0] for n in K]
    ys = [pos[n][1] for n in K]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    def place(n, px, py):
        fx = (pos[n][0] - x0) / max(x1 - x0, 1e-9)
        fy = (pos[n][1] - y0) / max(y1 - y0, 1e-9)
        return px + 30 + fx * (pw - 60), py + 26 + fy * (ph - 58)

    parts = []
    counts = collections.Counter(sec_of.get(n, "not_a_sector") for n in K)
    for i, group in enumerate(SPOTLIGHT):
        px = (i % cols) * (pw + gap * 1.5)
        py = (i // cols) * (ph + gap * 2.4) + 24
        lit = {n for n in K if sec_of.get(n) == group}
        # Only edges touching the lit sector are drawn: the whole core is a
        # grey mat at panel size, and the panel's question is which edges
        # this sector carries.
        segs = [(place(a, px, py), place(b, px, py),
                 2 if (a in lit and b in lit) else 1)
                for a, b in K.edges() if a in lit or b in lit]
        parts.append(draw.curved_edges(
            segs, mode, bow=0.10,
            width_of=lambda k: 1.5 if k == 2 else 0.7,
            opacity_of=lambda k: 0.55 if k == 2 else 0.20,
            colour_of=lambda k: p["series"][0] if k == 2 else p["edge"]))
        dim, bright = [], []
        for n in K:
            x, y = place(n, px, py)
            (bright if n in lit else dim).append({
                "id": n, "x": x, "y": y,
                "r": 4.4 if n in lit else 2.0,
                "color": p["series"][0] if n in lit else p["other"],
                "tip": (d["firms"].get(n, {}).get("name") or n),
            })
        parts.append(f'<g opacity="0.5">{draw.circles(dim, mode, ring=1.0)}</g>')
        parts.append(draw.hoverable(bright, mode, ring=1.4))
        parts.append(_axis_text(
            mode, px + 30, py + 14,
            f"{_en(d, group)} — {len(lit)} / {K.number_of_nodes()}",
            "start", AXIS_FONT))
    height = 24 + 2 * (ph + gap * 2.4) + 8
    title = {"fr": "fig. 48 — Le cœur du réseau, secteur par secteur",
             "en": "fig. 48 — The network core, one sector at a time"}[lang]
    caption = {
        "fr": (f"Les {K.number_of_nodes()} firmes du cœur d'interlock de la "
               f"figure 1, aux coordonnées de la figure 1, quatre fois : un "
               f"secteur allumé par panneau, ses arêtes en bleu, le reste du "
               f"cœur en gris. La finance en occupe "
               f"{counts['finance']} sur {K.number_of_nodes()} "
               f"({counts['finance'] / K.number_of_nodes():.0%}) ; les mines, "
               f"presque identiques en nombre de firmes sur l'ensemble du "
               f"graphe (530 contre 533), n'en occupent que "
               f"{counts['mining']}. Seules les arêtes touchant le secteur "
               f"allumé sont tracées : les {K.number_of_edges():,} arêtes du "
               f"cœur forment un tapis gris dans un panneau de cette taille."),
        "en": (f"The {K.number_of_nodes()} firms of figure 1's interlock core, "
               f"at figure 1's coordinates, four times: one sector lit per "
               f"panel, its edges in blue, the rest of the core in grey. "
               f"Finance holds {counts['finance']} of "
               f"{K.number_of_nodes()} ({counts['finance'] / K.number_of_nodes():.0%}); "
               f"mining, almost identical in firm count across the whole graph "
               f"(530 against 533), holds {counts['mining']}. Only edges "
               f"touching the lit sector are drawn — the core's "
               f"{K.number_of_edges():,} edges are a grey mat at this size."),
    }[lang]
    table = ([{"fr": "Secteur", "en": "Sector"}[lang],
              {"fr": "Firmes au cœur", "en": "Firms in core"}[lang],
              {"fr": "Part du cœur", "en": "Share of core"}[lang]],
             [(_en(d, g), counts[g],
               f"{counts[g] / K.number_of_nodes():.0%}")
              for g, _ in counts.most_common(10) if g != "not_a_sector"])
    return "".join(parts), height, title, None, caption, table


# --- fig49: what removal costs -------------------------------------------
def fig_removal(d, mode, lang):
    import random

    p = PALETTE[mode]
    K, pos, sec_of = d["core"], d["pos"], d["sec_of"]
    if not K.number_of_nodes():
        return "", 40.0, "", None, "", None
    fin = sorted(n for n in K if sec_of.get(n) == "finance")
    rng = random.Random(REMOVAL_SEED)
    rand = rng.sample(sorted(K), len(fin))
    panels = [(None, {"fr": "le cœur entier", "en": "the whole core"}[lang]),
              (set(fin), {"fr": f"finance retirée ({len(fin)} firmes)",
                          "en": f"finance removed ({len(fin)} firms)"}[lang]),
              (set(rand), {"fr": f"{len(rand)} firmes au hasard",
                           "en": f"{len(rand)} random firms"}[lang])]
    pw, ph = W / 3 - 14, 330.0
    xs = [pos[n][0] for n in K]
    ys = [pos[n][1] for n in K]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    def place(n, px):
        fx = (pos[n][0] - x0) / max(x1 - x0, 1e-9)
        fy = (pos[n][1] - y0) / max(y1 - y0, 1e-9)
        return px + 16 + fx * (pw - 32), 30 + fy * (ph - 58)

    parts, lost_counts = [], []
    for i, (gone, label) in enumerate(panels):
        px = i * (pw + 21)
        gone = gone or set()
        kept = [(a, b) for a, b in K.edges() if a not in gone and b not in gone]
        lost = [(a, b) for a, b in K.edges() if a in gone or b in gone]
        lost_counts.append(len(lost))
        # The lost edges stay on the canvas as ghosts. A blank space cannot
        # show how much edge mass left with the sector, which is the point.
        if lost:
            parts.append(draw.curved_edges(
                [(place(a, px), place(b, px), 0) for a, b in lost], mode,
                bow=0.10, width_of=lambda _: 0.7,
                opacity_of=lambda _: 0.30,
                colour_of=lambda _: p["series"][1]))
        parts.append(draw.curved_edges(
            [(place(a, px), place(b, px), 0) for a, b in kept], mode,
            bow=0.10, width_of=lambda _: 0.6,
            opacity_of=lambda _: 0.22, colour_of=lambda _: p["edge"]))
        nodes = [{"id": n, "x": place(n, px)[0], "y": place(n, px)[1],
                  "r": 2.0 if n in gone else 3.4,
                  "color": p["series"][1] if n in gone else p["other"],
                  "tip": (d["firms"].get(n, {}).get("name") or n)}
                 for n in K]
        parts.append(draw.hoverable(nodes, mode, ring=1.2))
        parts.append(_axis_text(mode, px + 16, 16, label, "start", AXIS_FONT))
        parts.append(_axis_text(
            mode, px + 16, ph + 4,
            ({"fr": f"{len(kept):,} arêtes restantes",
              "en": f"{len(kept):,} edges left"}[lang]
             if gone else {"fr": f"{len(kept):,} arêtes",
                           "en": f"{len(kept):,} edges"}[lang]),
            "start", AXIS_FONT, muted=True))

    sec = {r["sector_group"]: r for r in d["sector"]}
    f, m = sec.get("finance", {}), sec.get("mining", {})
    title = {"fr": "fig. 49 — Ce que coûte le retrait",
             "en": "fig. 49 — What removal costs"}[lang]
    caption = {
        "fr": (f"Le même cœur, aux mêmes coordonnées, trois fois ; les arêtes "
               f"perdues restent en orange. Et le résultat s'inverse ici : "
               f"retirer la finance emporte {lost_counts[1]:,} des "
               f"{K.number_of_edges():,} arêtes du cœur, contre "
               f"{lost_counts[2]:,} pour autant de firmes tirées au hasard "
               f"dans le cœur lui-même. C'est attendu et instructif : le cœur est "
               f"constitué des 170 firmes de plus fort degré pondéré, donc un "
               f"tirage au hasard y est un tirage de moyeux. Le cœur ne peut "
               f"pas départager les secteurs. Sur le graphe entier, où le "
               f"tirage est vraiment quelconque, la finance s'en détache : "
               f"z = {f.get('giant_drop_z', '?')} contre "
               f"z = {m.get('giant_drop_z', '?')} pour les mines, à 533 et 530 "
               f"firmes ; et le coût se lit dans la distance, le chemin moyen "
               f"s'allongeant de {f.get('path_change', '?')} contre "
               f"{m.get('path_change', '?')}. Aucun secteur ne fragmente le "
               f"réseau — la composante géante reste à "
               f"{float(d['baseline'].get('giant_share', 0)):.1%}."),
        "en": (f"The same core, at the same coordinates, three times; lost "
               f"edges stay in orange. And the result inverts here: "
               f"removing finance takes {lost_counts[1]:,} of the core's "
               f"{K.number_of_edges():,} edges, against {lost_counts[2]:,} for "
               f"the same number of firms drawn at random from within the "
               f"core itself. That is expected and worth seeing: the core is the 170 "
               f"firms of highest weighted degree, so a random draw inside it "
               f"is a draw of hubs. The core cannot separate sectors. On the "
               f"whole graph, where the draw is genuinely arbitrary, finance "
               f"does separate: z = {f.get('giant_drop_z', '?')} against "
               f"z = {m.get('giant_drop_z', '?')} for mining, at 533 and 530 "
               f"firms; and the cost reads as distance, the mean path "
               f"lengthening by {f.get('path_change', '?')} against "
               f"{m.get('path_change', '?')}. No sector fragments the network "
               f"— the giant component stays at "
               f"{float(d['baseline'].get('giant_share', 0)):.1%}."),
    }[lang]
    legend = [(p["series"][1], {"fr": "retiré, et ses arêtes",
                               "en": "removed, and its edges"}[lang]),
              (p["other"], {"fr": "conservé", "en": "kept"}[lang])]
    table = ([{"fr": "Panneau", "en": "Panel"}[lang],
              {"fr": "Arêtes restantes", "en": "Edges left"}[lang],
              {"fr": "Arêtes perdues", "en": "Edges lost"}[lang]],
             [(lab, K.number_of_edges() - n, n)
              for (_, lab), n in zip(panels, lost_counts)])
    return "".join(parts), ph + 34.0, title, legend, caption, table


# --- fig50: a hub is not a broker ----------------------------------------
def fig_hub_broker(d, mode, lang):
    p = PALETTE[mode]
    G, cent, sec_of = d["full"], d["cent"], d["sec_of"]
    if not cent:
        return "", 40.0, "", None, "", None
    rows = [r for r in cent.values() if r["company_id"] in G]
    hubs = sorted((r for r in rows
                   if sec_of.get(r["company_id"]) == "finance"),
                  key=lambda r: -float(r["betweenness"]))[:3]
    brokers = sorted((r for r in rows if int(r["degree"]) >= 8),
                     key=lambda r: -int(r["broker_gap"]))[:3]
    picks = [(r, "hub") for r in hubs] + [(r, "broker") for r in brokers]
    if len(picks) < 6:
        return "", 40.0, "", None, "", None

    cols, pw, ph = 3, W / 3 - 12, 258.0
    parts = []
    for i, (r, kind) in enumerate(picks):
        cid = r["company_id"]
        px = (i % cols) * (pw + 18)
        py = (i // cols) * (ph + 40) + 26
        nbrs = sorted(G[cid], key=lambda n: -G.degree(n))[:EGO_MAX]
        H = ordered_subgraph(G, [cid] + nbrs)
        sub = normalise(layout(H, seed=7, iterations=180), pw - 40, ph - 60,
                        pad=10, pad_x=10)
        colour = p["series"][0] if kind == "hub" else p["series"][1]
        segs = [((sub[a][0] + px + 20, sub[a][1] + py + 22),
                 (sub[b][0] + px + 20, sub[b][1] + py + 22),
                 1 if cid in (a, b) else 0) for a, b in H.edges()]
        parts.append(draw.curved_edges(
            segs, mode, bow=0.12,
            width_of=lambda k: 1.4 if k else 0.7,
            opacity_of=lambda k: 0.6 if k else 0.24,
            colour_of=lambda k: colour if k else p["edge"]))
        nodes = [{"id": n, "x": sub[n][0] + px + 20, "y": sub[n][1] + py + 22,
                  "r": 6.4 if n == cid else 2.8,
                  "color": colour if n == cid else p["other"],
                  "tip": (d["firms"].get(n, {}).get("name") or n)} for n in H]
        parts.append(draw.hoverable(nodes, mode, ring=1.4))
        name = d["firms"].get(cid, {}).get("name") or cid
        parts.append(_axis_text(mode, px + 20, py + 12,
                                trim_to_width(name, AXIS_FONT, pw - 44),
                                "start", AXIS_FONT))
        parts.append(_axis_text(
            mode, px + 20, py + ph - 22,
            f"deg {r['degree']} · btw {float(r['betweenness']):.4f} · "
            f"gap {int(r['broker_gap']):+,}".replace("-", "−"),
            "start", AXIS_FONT, muted=True))
    height = 26 + 2 * (ph + 40)
    title = {"fr": "fig. 50 — Un moyeu n'est pas un courtier",
             "en": "fig. 50 — A hub is not a broker"}[lang]
    caption = {
        "fr": ("En haut, les trois firmes de la finance à la plus forte "
               "bétweenness ; en bas, les trois plus forts écarts de courtage "
               "du réseau. Chaque panneau montre le voisinage de la firme, "
               "coupé aux 22 voisins de plus fort degré. Le moyeu est une "
               "étoile : ses voisins se connaissent déjà, et le retirer ne "
               "coupe presque rien. Le courtier est un pont : peu de voisins, "
               "mais des voisins qui ne se connaissent pas. À noter : les "
               "trois firmes de finance de plus forte bétweenness ont un "
               "écart de courtage proche de zéro ; la moyenne de −122 du "
               "secteur vient de ses nombreuses firmes de degré moyen et de "
               "faible bétweenness, non de ses sommets."),
        "en": ("Top: the three finance firms with the highest betweenness. "
               "Bottom: the three highest broker gaps in the network. Each "
               "panel is the firm's neighbourhood, cut to its 22 "
               "highest-degree neighbours. The hub is a star — its neighbours "
               "already know each other, and removing it cuts little. The "
               "broker is a bridge: few neighbours, but neighbours who do not "
               "know each other. Note that the three highest-betweenness "
               "finance firms have broker gaps near zero: the sector's mean of "
               "−122 comes from its many mid-degree, low-betweenness firms, "
               "not from its top."),
    }[lang]
    legend = [(p["series"][0], {"fr": "moyeu (finance)",
                               "en": "hub (finance)"}[lang]),
              (p["series"][1], {"fr": "courtier", "en": "broker"}[lang])]
    table = ([{"fr": "Firme", "en": "Firm"}[lang],
              {"fr": "Type", "en": "Kind"}[lang],
              {"fr": "Secteur", "en": "Sector"}[lang],
              {"fr": "Degré", "en": "Degree"}[lang],
              {"fr": "Bétweenness", "en": "Betweenness"}[lang],
              {"fr": "Écart", "en": "Gap"}[lang]],
             [((d["firms"].get(r["company_id"], {}).get("name")
                or r["company_id"]), kind,
               _en(d, sec_of.get(r["company_id"], "?")),
               r["degree"], f"{float(r['betweenness']):.5f}",
               r["broker_gap"]) for r, kind in picks])
    return "".join(parts), height, title, legend, caption, table


# --- fig51: shells outward from a sector ---------------------------------
SHELL_MAX = 3           # shells drawn; beyond this the rings are a few dozen
SHELL_SAMPLE = 900      # seed-to-shell-1 edges drawn, sampled
GOLDEN = 2.399963229728653   # radians; the sunflower angle


def _shells(G, seed):
    """Multi-source BFS: shortest hop count from any firm of the sector."""
    dist = {n: 0 for n in seed}
    frontier, d = list(seed), 0
    while frontier:
        d += 1
        nxt = []
        for u in frontier:
            for v in G[u]:
                if v not in dist:
                    dist[v] = d
                    nxt.append(v)
        frontier = nxt
    return dist


def _fill_annulus(items, cx, cy, r_in, r_out, phase=0.0):
    """Place items evenly through an annulus, not on its edge.

    The first version put every node of a shell exactly on the ring line, so
    3,684 firms became a 1px band of overprinted dots and the difference the
    figure exists to show was invisible. Filling the annulus by area — radius
    from the square root of the index — gives uniform visual density, which is
    what lets the *boundary* carry the meaning.
    """
    import math
    n = max(len(items), 1)
    pos = {}
    for i, item in enumerate(items):
        t = (i + 0.5) / n
        rad = math.sqrt(r_in * r_in + t * (r_out * r_out - r_in * r_in))
        ang = phase + i * GOLDEN
        pos[item] = (cx + rad * math.cos(ang), cy + rad * math.sin(ang))
    return pos


def fig_shells(d, mode, lang):
    """How much of the network sits one step from a sector's boards.

    Radii come from cumulative firm counts — r_k = R * sqrt(cum_k / N) — so
    **area is proportional to the number of firms** and the shell-1 frontier
    lands where that share of the network ends. That is the whole figure: for
    finance the frontier sits at sqrt(0.704) of the radius, for mining at
    sqrt(0.575), and the tinted region is visibly larger.
    """
    import math
    import random

    p = PALETTE[mode]
    G, sec_of = d["full"], d["sec_of"]
    if not G.number_of_nodes():
        return "", 40.0, "", None, "", None
    N = G.number_of_nodes()
    groups = ["finance", "mining"]
    pw, ph, R = W / 2 - 10, 560.0, 250.0
    parts, stats = [], {}
    rng = random.Random(5)
    for i, group in enumerate(groups):
        cx, cy = pw / 2 + i * (pw + 20), ph / 2 + 14
        seed = sorted(n for n in G if sec_of.get(n) == group)
        dist = _shells(G, seed)
        shells = collections.Counter(dist.values())
        stats[group] = (len(seed), shells, N - len(dist))

        # Cumulative radii: area per shell tracks its firm count.
        cum, radii = 0, [0.0]
        for k in range(0, SHELL_MAX + 2):
            cum += shells.get(k, 0)
            radii.append(R * math.sqrt(min(cum / N, 1.0)))
        pos = {}
        for k in range(0, SHELL_MAX + 1):
            members = sorted((n for n, dd in dist.items() if dd == k),
                             key=lambda n: (sec_of.get(n, ""), n))
            if members:
                pos.update(_fill_annulus(members, cx, cy, radii[k],
                                        radii[k + 1], phase=k * 0.9))

        # The one-step region, tinted. This is the comparison: a reader sees
        # the area, not a percentage.
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                     f'r="{radii[2]:.1f}" fill="{p["series"][0]}" '
                     f'fill-opacity="0.07"/>')
        cross = [(a, b) for a, b in G.edges()
                 if a in pos and b in pos
                 and {dist.get(a), dist.get(b)} == {0, 1}]
        if len(cross) > SHELL_SAMPLE:
            cross = rng.sample(sorted(cross), SHELL_SAMPLE)
        parts.append(draw.curved_edges(
            [(pos[a], pos[b], 0) for a, b in cross], mode, bow=0.05,
            width_of=lambda _: 0.45, opacity_of=lambda _: 0.10,
            colour_of=lambda _: p["series"][0]))
        dots = []
        for n, (x, y) in pos.items():
            k = dist[n]
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" '
                        f'r="{2.2 if k == 0 else 1.5:.1f}" '
                        f'fill="{p["series"][0] if k == 0 else p["other"]}" '
                        f'fill-opacity="{0.95 if k == 0 else 0.62}"/>')
        parts.append("".join(dots))
        # The frontier itself, drawn last so it sits over the dots.
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                     f'r="{radii[2]:.1f}" fill="none" '
                     f'stroke="{p["series"][0]}" stroke-width="2"/>')
        for k in (3, 4):
            if k < len(radii) and shells.get(k - 1):
                parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                             f'r="{radii[k]:.1f}" fill="none" '
                             f'stroke="{p["hairline"]}" stroke-width="1"/>')
        within = (shells[0] + shells[1]) / N
        parts.append(_axis_text(mode, cx, 12, _en(d, group), "middle",
                                AXIS_FONT))
        parts.append(draw.halo_text(
            mode, cx, cy - radii[2] - 7,
            ({"fr": f"un pas : {within:.1%} du réseau",
              "en": f"one step: {within:.1%} of the network"}[lang]),
            "middle", font=AXIS_FONT, weight="600"))
        parts.append(_axis_text(
            mode, cx, ph + 26,
            ({"fr": f"{shells[0]:,} firmes du secteur · "
                    f"{shells[1]:,} à un pas · {shells[2]:,} à deux",
              "en": f"{shells[0]:,} firms in the sector · "
                    f"{shells[1]:,} one step out · {shells[2]:,} two"}[lang]),
            "middle", AXIS_FONT, muted=True))

    fin_within = (stats["finance"][1][0] + stats["finance"][1][1]) / N
    min_within = (stats["mining"][1][0] + stats["mining"][1][1]) / N
    title = {"fr": "fig. 51 — Tout est à un pas d'une banque",
             "en": "fig. 51 — Everything is one step from a bank"}[lang]
    caption = {
        "fr": (f"Les {N:,} firmes du graphe d'interlock, placées par nombre de "
               f"pas depuis les conseils d'un secteur : le secteur au centre, "
               f"puis une couronne par pas. Les rayons viennent des effectifs "
               f"cumulés — l'aire est proportionnelle au nombre de firmes — "
               f"donc la ligne bleue tombe là où s'arrête la part du réseau "
               f"atteinte en un pas. À gauche la finance "
               f"({stats['finance'][0]} firmes), à droite les mines "
               f"({stats['mining'][0]}), presque exactement la même taille : "
               f"{fin_within:.1%} du réseau contre {min_within:.1%}. C'est le "
               f"même résultat que les tests de retrait, en géométrie. Les "
               f"arêtes sont un échantillon des liens du centre vers la "
               f"première couronne ({SHELL_SAMPLE:,} sur "
               f"{G.number_of_edges():,}) et ne servent que de texture."),
        "en": (f"The {N:,} firms of the interlock graph, placed by how many "
               f"steps they sit from a sector's boards: the sector at the "
               f"centre, one band per step. Radii come from cumulative firm "
               f"counts — area is proportional to the number of firms — so the "
               f"blue line falls where the share of the network reachable in "
               f"one step ends. Finance on the left ({stats['finance'][0]} "
               f"firms), mining on the right ({stats['mining'][0]}), almost "
               f"exactly the same size: {fin_within:.1%} of the network "
               f"against {min_within:.1%}. Same result as the removal tests, "
               f"in geometry. The edges are a sample of centre-to-first-band "
               f"ties ({SHELL_SAMPLE:,} of {G.number_of_edges():,}) and are "
               f"there as texture only."),
    }[lang]
    legend = [(p["series"][0], {"fr": "le secteur lui-même",
                               "en": "the sector itself"}[lang]),
              (p["other"], {"fr": "un, deux ou trois pas",
                            "en": "one, two or three steps out"}[lang])]
    table = ([{"fr": "Pas", "en": "Steps"}[lang]] + [_en(d, g) for g in groups],
             [[str(k)] + [f"{stats[g][1][k]:,}" for g in groups]
              for k in range(0, SHELL_MAX + 1)]
             + [[{"fr": "hors d'atteinte", "en": "unreachable"}[lang]]
                + [f"{stats[g][2]:,}" for g in groups]])
    return "".join(parts), ph + 34.0, title, legend, caption, table


# --- fig52: the core, placed by centrality -------------------------------
def fig_centrality_radial(d, mode, lang):
    """Radius is betweenness rank, so the centre of the picture is the centre
    of the network. Finance is coloured; you can see where it sits."""
    import math

    p = PALETTE[mode]
    K, cent, sec_of = d["core"], d["cent"], d["sec_of"]
    if not K.number_of_nodes():
        return "", 40.0, "", None, "", None
    order = sorted(K, key=lambda n: (-float(cent.get(n, {}).get("betweenness", 0)), n))
    n = len(order)
    cx, cy, rmax, height = W / 2, 330.0, 288.0, 660.0
    pos = {}
    for i, node in enumerate(order):
        # radius from rank, angle from the golden spiral: deterministic, and
        # the exponent keeps the middle from overcrowding.
        rad = rmax * ((i + 0.6) / n) ** 0.62
        ang = i * GOLDEN
        pos[node] = (cx + rad * math.cos(ang) * 1.42, cy + rad * math.sin(ang))
    fin = {node for node in K if sec_of.get(node) == "finance"}
    segs = [(pos[a], pos[b], 2 if (a in fin and b in fin)
             else 1 if (a in fin or b in fin) else 0)
            for a, b in K.edges()]
    body = [draw.curved_edges(
        segs, mode, bow=0.10,
        width_of=lambda k: 1.2 if k == 2 else 0.7 if k == 1 else 0.5,
        opacity_of=lambda k: 0.42 if k == 2 else 0.20 if k == 1 else 0.10,
        colour_of=lambda k: p["series"][0] if k else p["edge"])]
    hi = max(float(cent.get(node, {}).get("betweenness", 0)) for node in K) or 1
    nodes = []
    for node in order:
        b = float(cent.get(node, {}).get("betweenness", 0))
        nodes.append({
            "id": node, "x": pos[node][0], "y": pos[node][1],
            "r": draw.area_radius(b, hi, 11.0, 2.6),
            "color": p["series"][0] if node in fin else p["other"],
            "label": (d["firms"].get(node, {}).get("name") or node),
            "tip": (f"{d['firms'].get(node, {}).get('name') or node} — "
                    f"{_en(d, sec_of.get(node, '?'))}, betweenness rank "
                    f"{order.index(node) + 1} of {n}"),
        })
    body.append(draw.hoverable(nodes, mode))
    for nd, x, y, anchor in draw.place_labels(
            [x for x in nodes if x["id"] in fin][:14], W, height,
            max_width=200.0):
        body.append(draw.halo_text(mode, x, y, nd["label"], anchor))
    # Three faint guide ellipses at quarter, half and three-quarter rank.
    for frac in (0.25, 0.55, 0.85):
        rad = rmax * frac ** 0.62
        body.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
                    f'rx="{rad * 1.42:.1f}" ry="{rad:.1f}" fill="none" '
                    f'stroke="{p["hairline"]}" stroke-width="1"/>')
    top40 = collections.Counter(sec_of.get(x, "?") for x in order[:40])
    title = {"fr": "fig. 52 — Le cœur, placé par centralité",
             "en": "fig. 52 — The core, placed by centrality"}[lang]
    caption = {
        "fr": (f"Les {n} firmes du cœur d'interlock. Le rayon est le rang de "
               f"bétweenness : le centre de l'image est le centre du réseau, "
               f"et la position n'est pas le produit d'un algorithme de force "
               f"mais d'une quantité mesurée. La finance est en bleu. "
               f"{top40['finance']} des 40 firmes les plus intermédiaires du "
               f"cœur sont des firmes de finance, et son rang moyen est 54,4 "
               f"contre 90,8 pour les mines. L'angle est une spirale d'or : il "
               f"ne veut rien dire, il ne sert qu'à écarter les nœuds."),
        "en": (f"The {n} firms of the interlock core. Radius is betweenness "
               f"rank, so the centre of the picture is the centre of the "
               f"network and position is a measured quantity rather than the "
               f"output of a force algorithm. Finance is in blue. "
               f"{top40['finance']} of the core's 40 most-between firms are "
               f"finance firms, and its mean rank is 54.4 against mining's "
               f"90.8. The angle is a golden spiral: it means nothing and only "
               f"serves to spread the nodes apart."),
    }[lang]
    legend = [(p["series"][0], {"fr": "banque, finance, assurance",
                               "en": "banking, finance and insurance"}[lang]),
              (p["other"], {"fr": "tous les autres secteurs",
                            "en": "every other sector"}[lang])]
    table = ([{"fr": "Rang", "en": "Rank"}[lang],
              {"fr": "Firme", "en": "Firm"}[lang],
              {"fr": "Secteur", "en": "Sector"}[lang],
              {"fr": "Bétweenness", "en": "Betweenness"}[lang]],
             [(i + 1, (d["firms"].get(x, {}).get("name") or x),
               _en(d, sec_of.get(x, "?")),
               f"{float(cent.get(x, {}).get('betweenness', 0)):.5f}")
              for i, x in enumerate(order[:30])])
    return "".join(body), height, title, legend, caption, table


FIGURES = [
    ("fig51_steps_from_finance", fig_shells),
    ("fig52_core_by_centrality", fig_centrality_radial),
    ("fig47_sector_graph", fig_sector_graph),
    ("fig48_core_spotlight", fig_core_spotlight),
    ("fig49_removal_cost", fig_removal),
    ("fig50_hub_or_broker", fig_hub_broker),
]


def render_page(d, lang):
    title = {"fr": "Quel secteur est au centre de l'empire",
             "en": "Which sector is central to the empire"}[lang]
    lede = {
        "fr": ("La réponse est la banque et la finance, sur toutes les mesures "
               "qui survivent à un contrôle de taille — et la finance est un "
               "moyeu, pas un courtier. Les mesures sont dans "
               "sector_centrality.csv ; voici les quatre images."),
        "en": ("The answer is banking and finance, on every measure that "
               "survives a size control — and finance is a hub, not a broker. "
               "The measures are in sector_centrality.csv; these are the four "
               "pictures."),
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
    with open(os.path.join(out_dir, "sector_network.html"), "w",
              encoding="utf-8") as fh:
        fh.write(render_page(d, args.lang))
    print(f"wrote {written} sector-network figures + sector_network.html to "
          f"{os.path.relpath(out_dir, os.path.dirname(FIG_DIR))}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
