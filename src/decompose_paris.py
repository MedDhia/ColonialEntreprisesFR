"""Stage 24 - why Paris recedes: composition, not centrality.

    python3 src/decompose_paris.py

    data/processed/paris_decomposition.csv   one row per period
    data/processed/paris_entry_exit.csv      one row per transition x stratum

§5p established that Paris's share of the drawable ties falls in every period,
63.5% to 26.2%, and that the fall survives being recomputed on firms with a
street address alone. It did not say **why**, and the obvious reading — that the
colonial economy decentralised — is only one of several the data can tell apart.

## The decomposition

A tie touches Paris when either firm is a Paris firm, so the share of ties
touching Paris is driven by two quantities and no others: how large a share of
the active firms sit in Paris, and how well connected a Paris firm is relative
to everyone else. This stage measures both.

`degree_ratio` is the mean degree of Paris firms over the mean degree of the
other placed firms, inside the period's own subgraph. **It is flat** — 1.25,
1.31, 1.39, 1.16, 1.21, with no trend — while the Paris share of firms falls
from 36.0% to 12.1%. A Paris firm in the 1960s is as disproportionately
connected as a Paris firm in the 1890s. Paris did not stop being a hub; the
record stopped being mostly Parisian.

## Composition can only change one way, and that is a limitation

A firm carries **one anchor for all time** in this dataset: `place_on_map`
assigns a position per firm, not per firm-period, because the sources give a
head office and not a history of one. So a firm that moved its seat from
Marseille to Paris in 1925 is at one of them in every panel, and the
geographic composition of a period can change *only* through firms entering
and leaving the record. The entry/exit table is therefore the whole of the
story, by construction rather than by finding.

## Entry, not exit

Firms entering each period are consistently far less Parisian than the
standing stock they join — 22.5% against 36.0%, then 10.2/26.2, 9.1/19.1,
7.8/19.2. Firms leaving are about as Parisian as the stock they leave, and in
the first three transitions Paris firms are slightly *more* persistent than
average. Nothing pushes Paris out; something non-Parisian arrives.

## What "entering the record" means changes over time, and that is the finding

A firm enters a period when it has an interlock **dated** to it, which is a
fact about when Mennevée wrote, not about when the firm was founded. Those
come apart, and the stage measures how far:

| Transition | entrants with a founding year | founded *in* that period |
|---|---|---|
| pre-1914 → 1914–1929 | 728 | **591 (81%)** |
| 1914–1929 → 1930–1944 | 507 | 188 (37%) |
| 1930–1944 → 1945–1962 | 174 | 33 (19%) |
| 1945–1962 → post-1962 | 62 | **1 (2%)** |

Early on the entrants are genuinely new firms, and 420 of those 591 are
outside Paris: that is colonial company formation outpacing metropolitan, and
it supports an economic reading. By the last two transitions the entrants are
old firms the compiler had not yet written about, and the same reading does
not hold.

**The founding-year field is not evenly recorded**, which is why the table is
also cut by stratum. 70.2% of metropolitan placed firms carry one against
49.9% of empire firms, and firms with a year are twice as Parisian as firms
without (25.3% against 12.4%). Since metropolitan firms are older on average,
that bias pushes in exactly the direction of the observed trend. It does not
produce it: the collapse holds inside each stratum separately — metropole
82 → 32 → 7 → 0%, empire 82 → 38 → 22 → 2%.

**What this stage does not settle.** Whether the compiler's later volumes turn
to older colonial firms because his interests moved, because his sources did,
or because the firms themselves became newsworthy, is not in the data. The
finding is narrower and firmer: the geographic trend is compositional, the
composition moves through entry, and entry stops meaning *new firm* after the
1930s.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_network import PERIODS, read_csv, write_csv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
BY_PERIOD = os.path.join(PROC, "paris_decomposition.csv")
ENTRY_EXIT = os.path.join(PROC, "paris_entry_exit.csv")

ANCHOR = "Paris"
STRATA = ["all", "metropole", "empire"]
YEAR_RE = re.compile(r"\b(1[5-9]\d\d)\b")
# The catalogue's two founding-date fields, in the order they are trusted.
YEAR_FIELDS = ("year_start_listed", "founded_date_observed")


def founded(rec: dict) -> int | None:
    """A founding year from the catalogue, or None.

    Recorded for 30% of companies and **not evenly** — see the module
    docstring. Every use of it in this file is also cut by stratum.
    """
    for key in YEAR_FIELDS:
        m = YEAR_RE.search(rec.get(key) or "")
        if m:
            return int(m.group(1))
    return None


def load() -> tuple[dict, dict, dict]:
    companies = {r["company_id"]: r for r in read_csv(os.path.join(PROC, "companies.csv"))}
    path = os.path.join(PROC, "company_map_positions.csv")
    if not os.path.exists(path):
        raise SystemExit("run: python3 src/place_on_map.py")
    placed = {r["company_id"]: r for r in read_csv(path) if r["lat"]}
    edges: dict[str, list] = collections.defaultdict(list)
    for r in read_csv(os.path.join(PROC, "edges_company_interlock_by_period.csv")):
        a, b = r["company_id_1"], r["company_id_2"]
        if a in placed and b in placed:
            edges[r["period"]].append((a, b))
    return companies, placed, edges


def per_period(placed, edges) -> list[dict]:
    rows = []
    for name, _lo, _hi in PERIODS:
        es = edges.get(name, [])
        deg: collections.Counter = collections.Counter()
        for a, b in es:
            deg[a] += 1
            deg[b] += 1
        firms = set(deg)
        paris = {f for f in firms if placed[f]["anchor"] == ANCHOR}
        other = firms - paris
        d_paris = sum(deg[f] for f in paris) / max(len(paris), 1)
        d_other = sum(deg[f] for f in other) / max(len(other), 1)
        touching = sum(1 for a, b in es if a in paris or b in paris)
        rows.append({
            "period": name,
            "n_firms": len(firms), "n_paris_firms": len(paris),
            "share_paris_firms": f"{len(paris) / max(len(firms), 1):.4f}",
            "n_edges": len(es), "n_paris_edges": touching,
            "share_paris_edges": f"{touching / max(len(es), 1):.4f}",
            "mean_degree_paris": f"{d_paris:.3f}",
            "mean_degree_other": f"{d_other:.3f}",
            # The whole argument in one column: if this is flat, the falling
            # tie share is composition and not a loss of centrality.
            "degree_ratio": f"{d_paris / d_other:.4f}" if d_other else "",
        })
    return rows


def entry_exit(companies, placed, edges) -> list[dict]:
    order = [n for n, _lo, _hi in PERIODS]
    window = {n: (lo, hi) for n, lo, hi in PERIODS}
    active = {n: {x for a, b in edges.get(n, []) for x in (a, b)} for n in order}

    def share_paris(fs):
        return sum(1 for f in fs if placed[f]["anchor"] == ANCHOR) / max(len(fs), 1)

    rows = []
    for a, b in zip(order, order[1:]):
        lo, hi = window[b]
        for stratum in STRATA:
            def keep(fs):
                if stratum == "all":
                    return set(fs)
                return {f for f in fs if placed[f]["group"] == stratum}

            base, nxt = keep(active[a]), keep(active[b])
            stay, gone, came = base & nxt, base - nxt, nxt - base
            dated = {f: founded(companies[f]) for f in came
                     if f in companies and founded(companies[f])}
            in_period = [f for f, y in dated.items() if lo <= y <= hi]
            rows.append({
                "from_period": a, "to_period": b, "stratum": stratum,
                "n_base": len(base), "share_paris_base": f"{share_paris(base):.4f}",
                "n_stay": len(stay), "share_paris_stay": f"{share_paris(stay):.4f}",
                "n_exit": len(gone), "share_paris_exit": f"{share_paris(gone):.4f}",
                "n_enter": len(came), "share_paris_enter": f"{share_paris(came):.4f}",
                "n_enter_dated": len(dated),
                "n_enter_founded_in_period": len(in_period),
                "share_founded_in_period":
                    f"{len(in_period) / max(len(dated), 1):.4f}" if dated else "",
                "n_founded_in_period_outside_paris":
                    sum(1 for f in in_period if placed[f]["anchor"] != ANCHOR),
            })
    return rows


def field_coverage(companies, placed) -> None:
    """The bias in the founding-year field, printed so it is never implicit."""
    have = [f for f in placed if f in companies and founded(companies[f])]
    lack = [f for f in placed if f in companies and not founded(companies[f])]

    def ps(fs):
        return 100 * sum(1 for f in fs if placed[f]["anchor"] == ANCHOR) / max(len(fs), 1)

    print(f"\nfounding year recorded for {len(have):,} of {len(placed):,} placed firms",
          file=sys.stderr)
    print(f"  with a year: {ps(have):.1f}% Paris | without: {ps(lack):.1f}% Paris "
          f"— the field is twice as likely on a Paris firm", file=sys.stderr)
    by = collections.Counter()
    tot = collections.Counter()
    for f in placed:
        tot[placed[f]["group"]] += 1
        if f in companies and founded(companies[f]):
            by[placed[f]["group"]] += 1
    for g in ("metropole", "empire", "foreign"):
        if tot[g]:
            print(f"  {g:10} {by[g]:5,}/{tot[g]:5,} = {100 * by[g] / tot[g]:5.1f}%",
                  file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.parse_args()

    companies, placed, edges = load()
    periods = per_period(placed, edges)
    moves = entry_exit(companies, placed, edges)

    write_csv(BY_PERIOD, periods, list(periods[0]))
    write_csv(ENTRY_EXIT, moves, list(moves[0]))

    print("\nParis, period by period:", file=sys.stderr)
    print(f"  {'period':12} {'firms':>7} {'%firms':>7} {'%ties':>7} {'deg ratio':>10}",
          file=sys.stderr)
    for r in periods:
        print(f"  {r['period']:12} {int(r['n_firms']):7,} "
              f"{100 * float(r['share_paris_firms']):6.1f}% "
              f"{100 * float(r['share_paris_edges']):6.1f}% "
              f"{float(r['degree_ratio']):10.2f}", file=sys.stderr)
    ratios = [float(r["degree_ratio"]) for r in periods if r["degree_ratio"]]
    print(f"  degree ratio stays in [{min(ratios):.2f}, {max(ratios):.2f}] — "
          f"Paris firms never stop being better connected", file=sys.stderr)

    print("\nentry and exit (all firms):", file=sys.stderr)
    for r in moves:
        if r["stratum"] != "all":
            continue
        print(f"  {r['from_period']} -> {r['to_period']:11} "
              f"enter {int(r['n_enter']):5,} at "
              f"{100 * float(r['share_paris_enter']):5.1f}% Paris vs "
              f"{100 * float(r['share_paris_base']):5.1f}% in the standing stock; "
              f"{int(r['n_enter_founded_in_period']):4,}/{int(r['n_enter_dated']):4,} "
              f"({100 * float(r['share_founded_in_period'] or 0):3.0f}%) founded in-period",
              file=sys.stderr)
    field_coverage(companies, placed)


if __name__ == "__main__":
    main()
