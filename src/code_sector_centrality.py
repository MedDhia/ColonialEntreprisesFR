"""Stage 18 - how central each sector is to the interlock network.

    python3 src/code_sector_centrality.py
    python3 src/code_sector_centrality.py --sims 200   # a tighter null

Writes `sector_centrality.csv`, one row per sector group. It exists because
"which sector is most central" has at least six defensible answers and they do
not agree, so the file carries all of them and the figures cite it rather than
recomputing.

**The size confound is the whole problem.** A sector with more firms and bigger
boards has more edges for reasons that have nothing to do with position.
Finance holds 15,399 board seats against mining's 9,646, so any raw count puts
finance ahead before position is considered at all. Three of the columns here
exist only to strip that out:

- `deg_per_seat`, `btw_per_seat` — normalised by board seats, not by firm count.
- `giant_drop_z`, `giant_drop_p` — the removal test against a **size-matched
  null**: delete the sector, then compare the loss to deleting the same *number*
  of firms at random, `--sims` times. This is the column that separates finance
  from mining, which are 533 and 530 firms and therefore identical in size.
- `path_change` — mean shortest-path length after removing the sector, on a
  fixed 120-source sample. Fragmentation shows nothing in this graph (the giant
  component is 98.6% and no sector's removal breaks it), so distance is where
  the cost of removal actually appears.

**What the removal test does not license.** Deleting a sector from an observed
graph is a descriptive operation on this dataset, not a counterfactual about
the empire. It says the network as recorded routes more of its connectivity
through finance than through an equally large random slice; it does not say the
economy would have been less connected without banks, because the firms would
not have existed, the directors would have sat elsewhere, and the compiler's
coverage is uneven by sector.
"""

from __future__ import annotations

import argparse
import collections
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import networkx as nx  # noqa: E402

import sectors as S  # noqa: E402
from build_network import read_csv, write_csv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIN_FIRMS = 25        # below this a sector's measures are noise
PATH_SOURCES = 120    # sampled sources for mean path length
PATH_SEED = 11
NULL_SEED = 17
DEFAULT_SIMS = 60


def mean_path(H, k: int = PATH_SOURCES, seed: int = PATH_SEED) -> float:
    """Mean shortest-path length over `k` sampled sources in the giant component.

    Sampled, not exact: an exact all-pairs run on 5,989 nodes is not the point,
    and the sources are drawn from a sorted list under a fixed seed so the
    figure is reproducible. Same convention as `make_network_figures`.
    """
    if not H.number_of_nodes():
        return float("nan")
    big = max(nx.connected_components(H), key=len)
    Hs = H.subgraph(big)
    rng = random.Random(seed)
    src = rng.sample(sorted(Hs), min(k, Hs.number_of_nodes()))
    total = count = 0
    for s in src:
        for d in nx.single_source_shortest_path_length(Hs, s).values():
            if d:
                total += d
                count += 1
    return total / count if count else float("nan")


def giant_share(H) -> float:
    n = H.number_of_nodes()
    if not n:
        return 0.0
    return max(len(c) for c in nx.connected_components(H)) / n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=DEFAULT_SIMS,
                    help="size-matched null removals per sector")
    args = ap.parse_args()

    mapping = S.load_map()
    firms = {r["company_id"]: r for r in read_csv("companies.csv")}
    sec_of = {cid: S.sector_of(dict(r, company_id=cid), mapping)[0]
              for cid, r in firms.items()}
    english = {}
    for cid, r in firms.items():
        g, en, _ = S.sector_of(dict(r, company_id=cid), mapping)
        english[g] = en
    territory = {cid: (r.get("countries") or "").split("; ")[0]
                 for cid, r in firms.items()}

    seats: collections.Counter = collections.Counter()
    for row in read_csv("edges_person_company.csv"):
        if row.get("is_board_seat") == "1" and row.get("company_id"):
            seats[row["company_id"]] += 1

    cent = {r["company_id"]: r for r in read_csv("company_centrality.csv")}

    G = nx.Graph()
    for row in read_csv("edges_company_interlock.csv"):
        G.add_edge(row["company_id_1"], row["company_id_2"],
                   weight=int(row["weight"]))
    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()
    core = nx.core_number(G)
    kmax = max(core.values())
    deep = {n for n, k in core.items() if k == kmax}
    base_giant = giant_share(G)
    base_path = mean_path(G)
    print(f"interlock graph: {n_nodes:,} firms, {n_edges:,} edges; "
          f"giant {base_giant:.4f}, mean path {base_path:.4f}, "
          f"deepest core k={kmax} ({len(deep)} firms)", file=sys.stderr)

    # Edge-incidence and cross-territory counts, one pass.
    incident: collections.Counter = collections.Counter()
    cross: collections.Counter = collections.Counter()
    within: collections.Counter = collections.Counter()
    pairs: collections.Counter = collections.Counter()
    n_cross = 0
    for a, b in G.edges():
        sa, sb = sec_of.get(a, "not_a_sector"), sec_of.get(b, "not_a_sector")
        ta, tb = territory.get(a, ""), territory.get(b, "")
        is_cross = bool(ta and tb and ta != tb)
        n_cross += is_cross
        for s in {sa, sb}:
            incident[s] += 1
            if is_cross:
                cross[s] += 1
        if sa == sb:
            within[sa] += 1
        elif "not_a_sector" not in (sa, sb):
            pairs[tuple(sorted((sa, sb)))] += 1

    by_sector: dict[str, list[str]] = collections.defaultdict(list)
    for node in G:
        by_sector[sec_of.get(node, "not_a_sector")].append(node)

    rng = random.Random(NULL_SEED)
    all_nodes = sorted(G)
    rows = []
    for group, nodes in sorted(by_sector.items(), key=lambda kv: -len(kv[1])):
        if group == "not_a_sector" or len(nodes) < MIN_FIRMS:
            continue
        nodes = sorted(nodes)
        seat_total = sum(seats[n] for n in nodes)
        degrees = [G.degree(n) for n in nodes]
        btws = [float(cent[n]["betweenness"]) for n in nodes if n in cent]
        gaps = [int(cent[n]["broker_gap"]) for n in nodes if n in cent]

        H = G.copy()
        H.remove_nodes_from(nodes)
        drop = base_giant - giant_share(H)
        path_after = mean_path(H)

        sims = []
        for _ in range(args.sims):
            K = G.copy()
            K.remove_nodes_from(rng.sample(all_nodes, len(nodes)))
            sims.append(base_giant - giant_share(K))
        mu = statistics.mean(sims)
        sd = statistics.pstdev(sims)
        rows.append({
            "sector_group": group,
            "sector_group_en": english.get(group, group),
            "n_firms": len(nodes),
            "n_seats": seat_total,
            "mean_degree": f"{statistics.mean(degrees):.3f}",
            "median_degree": statistics.median(degrees),
            "deg_per_seat": f"{sum(degrees) / max(seat_total, 1):.4f}",
            "sum_betweenness": f"{sum(btws):.6f}",
            "mean_betweenness": f"{statistics.mean(btws):.8f}" if btws else "",
            "btw_per_seat": f"{sum(btws) / max(seat_total, 1) * 1e4:.4f}",
            "mean_broker_gap": f"{statistics.mean(gaps):.1f}" if gaps else "",
            "n_edges_incident": incident[group],
            "edge_share": f"{incident[group] / n_edges:.4f}",
            "n_edges_within": within[group],
            "cross_territory_share": (
                f"{cross[group] / max(incident[group], 1):.4f}"),
            "n_deep_core": sum(1 for n in nodes if n in deep),
            "giant_drop": f"{drop:+.5f}",
            "giant_drop_null_mean": f"{mu:+.5f}",
            "giant_drop_null_sd": f"{sd:.5f}",
            "giant_drop_z": f"{(drop - mu) / sd:+.2f}" if sd else "",
            "giant_drop_p": f"{sum(1 for s in sims if s >= drop) / len(sims):.3f}",
            "path_after": f"{path_after:.4f}",
            "path_change": f"{path_after - base_path:+.4f}",
        })

    write_csv("sector_centrality.csv", rows, list(rows[0].keys()) if rows
              else ["sector_group"])

    pair_rows = [{"sector_a": a, "sector_b": b, "n_interlocks": n,
                  "sector_a_en": english.get(a, a),
                  "sector_b_en": english.get(b, b)}
                 for (a, b), n in sorted(pairs.items(),
                                         key=lambda kv: (-kv[1], kv[0]))]
    write_csv("edges_sector_interlock.csv", pair_rows,
              ["sector_a", "sector_b", "sector_a_en", "sector_b_en",
               "n_interlocks"])

    write_csv("sector_centrality_baseline.csv", [{
        "n_firms": n_nodes, "n_edges": n_edges,
        "giant_share": f"{base_giant:.4f}",
        "mean_path_length": f"{base_path:.4f}",
        "path_sources": PATH_SOURCES, "path_seed": PATH_SEED,
        "null_sims": args.sims, "null_seed": NULL_SEED,
        "max_core_number": kmax, "max_core_size": len(deep),
        "cross_territory_share": f"{n_cross / n_edges:.4f}",
        "n_cross_sector_edges": sum(pairs.values()),
        "n_within_sector_edges": sum(within.values()),
    }], ["n_firms", "n_edges", "giant_share", "mean_path_length",
         "path_sources", "path_seed", "null_sims", "null_seed",
         "max_core_number", "max_core_size", "cross_territory_share",
         "n_cross_sector_edges", "n_within_sector_edges"])

    print(f"\n{'sector':<20}{'firms':>6}{'edge%':>7}{'btw':>9}"
          f"{'drop':>9}{'z':>7}{'p':>7}{'path':>8}", file=sys.stderr)
    for r in sorted(rows, key=lambda r: -float(r["giant_drop"])):
        print(f"{r['sector_group'][:19]:<20}{r['n_firms']:>6}"
              f"{float(r['edge_share']):>7.1%}{float(r['sum_betweenness']):>9.4f}"
              f"{float(r['giant_drop']):>+9.4f}{r['giant_drop_z']:>7}"
              f"{r['giant_drop_p']:>7}{r['path_change']:>8}", file=sys.stderr)


if __name__ == "__main__":
    main()
