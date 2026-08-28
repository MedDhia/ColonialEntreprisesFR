"""Betweenness centrality on the interlock network, computed once and cached.

    python3 src/centrality.py              # writes data/processed/company_centrality.csv
    python3 src/centrality.py --recompute  # ignore the cache

Betweenness asks a different question from degree. Degree counts how many
firms a firm shares directors with; betweenness counts how often it lies on
the shortest path between two firms that do *not* share one. A firm can have a
modest board and still be the only thing joining two blocs — that is a broker,
and brokerage is invisible to a degree-sized figure.

Three decisions, each of which changes the numbers:

- **Computed on the whole graph, not on a subset.** Betweenness is a global
  property: the shortest paths that matter run through firms outside any core
  you might draw. Computing it on the top 170 and calling it betweenness would
  be a different quantity wearing the same name. It is computed on the giant
  component of the interlock graph at `weight >= 1` (3,039 firms, 39,497
  ties), and figures then display the slice they display.
- **Exact, not sampled.** `networkx` will estimate from `k` pivot nodes in a
  few seconds; the exact Brandes run takes about a minute here, which is
  affordable, so there is no approximation to caveat.
- **Unweighted.** Edge weight in this graph is the number of shared directors
  - a measure of *strength*, not distance. Feeding it to a shortest-path
  algorithm would make heavily-interlocked pairs count as far apart, which is
  backwards. The standard treatment for interlock networks is the binary
  graph, and that is what this uses.

Isolated firms and the 46 outside the giant component have no betweenness in
any meaningful sense; they are written with 0 and flagged `in_giant = 0`.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_network import read_csv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "processed", "company_centrality.csv")

FIELDS = ["company_id", "name", "in_giant", "degree", "weighted_degree",
          "betweenness", "betweenness_rank", "degree_rank", "broker_gap"]


def compute(min_weight: int = 1) -> list[dict]:
    import networkx as nx

    from make_figures import build_interlock_graph

    companies = {r["company_id"]: r for r in read_csv("companies.csv")}
    G = build_interlock_graph(min_weight)
    giant = set(max(nx.connected_components(G), key=len)) if G else set()
    H = G.subgraph(giant).copy()

    print(f"betweenness on {H.number_of_nodes():,} firms, "
          f"{H.number_of_edges():,} ties (exact, unweighted)...", file=sys.stderr)
    bt = nx.betweenness_centrality(H, normalized=True)

    deg = dict(G.degree())
    wdeg = dict(G.degree(weight="weight"))
    rows = []
    for n in G.nodes():
        rows.append({
            "company_id": n,
            "name": companies.get(n, {}).get("name") or n,
            "in_giant": int(n in giant),
            "degree": deg[n],
            "weighted_degree": wdeg[n],
            "betweenness": round(bt.get(n, 0.0), 8),
        })

    # Ranks, so "high betweenness for its degree" is expressible without
    # comparing two quantities on incomparable scales.
    for key, field in (("betweenness", "betweenness_rank"), ("degree", "degree_rank")):
        for i, r in enumerate(sorted(rows, key=lambda r: -r[key]), start=1):
            r[field] = i
    for r in rows:
        # Positive = brokers more central than their board size suggests.
        r["broker_gap"] = r["degree_rank"] - r["betweenness_rank"]

    rows.sort(key=lambda r: r["betweenness_rank"])
    return rows


def load(recompute: bool = False) -> dict[str, dict]:
    """Cached centrality, keyed by company_id. Values are strings from CSV
    on the cached path, so callers coerce - the writers below round first."""
    if not recompute and os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8", newline="") as fh:
            return {r["company_id"]: r for r in csv.DictReader(fh)}
    rows = write(compute())
    return {r["company_id"]: {k: str(v) for k, v in r.items()} for r in rows}


def write(rows: list[dict]) -> list[dict]:
    with open(CACHE, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {os.path.relpath(CACHE, ROOT)}: {len(rows):,} firms",
          file=sys.stderr)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recompute", action="store_true")
    ap.add_argument("--min-weight", type=int, default=1)
    args = ap.parse_args()
    if not args.recompute and os.path.exists(CACHE):
        print(f"{os.path.relpath(CACHE, ROOT)} exists; --recompute to redo",
              file=sys.stderr)
        return
    rows = write(compute(args.min_weight))
    print("\ntop by betweenness:", file=sys.stderr)
    for r in rows[:10]:
        print(f"  {r['betweenness']:.5f}  deg {r['degree']:4d}  {r['name'][:58]}",
              file=sys.stderr)
    brokers = sorted(rows, key=lambda r: -r["broker_gap"])[:8]
    print("\nmost broker-like (betweenness rank far above degree rank):",
          file=sys.stderr)
    for r in brokers:
        print(f"  bt #{r['betweenness_rank']:<5d} deg #{r['degree_rank']:<5d} "
              f"{r['name'][:58]}", file=sys.stderr)


if __name__ == "__main__":
    main()
