"""A worked tour of the dataset, using the standard library only.

    python3 examples/explore.py

Prints: the best-connected directors, the densest company interlocks, the
sectoral and temporal shape of the data, the corporate-directorship relation,
and a traced provenance chain from one tie back to the citation it came from.

The last section is the point of the exercise. Any claim taken from this
dataset should be followable back to a named publication and date, and this
shows how.
"""

from __future__ import annotations

import csv
import os
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")


def load(name: str) -> list[dict]:
    path = os.path.join(PROC, name)
    if not os.path.exists(path):
        raise SystemExit(f"missing {path} - run the pipeline first (see README)")
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    docs = load("documents.csv")
    firms = load("companies.csv")
    people = load("persons_resolved.csv")
    edges = load("edges_person_company.csv")
    interlocks = load("edges_company_interlock.csv")
    period_il = load("edges_company_interlock_by_period.csv")
    corporate = load("edges_company_corporate.csv")
    affil = load("affiliations.csv")

    rule("1. Size of the dataset")
    print(f"  documents catalogued     {len(docs):>7,}")
    print(f"  companies                {len(firms):>7,}   "
          f"({sum(1 for f in firms if f['in_catalogue'] == '1'):,} with their own dossier)")
    print(f"  people                   {len(people):>7,}")
    print(f"  person-company ties      {len(edges):>7,}")
    print(f"  company interlock edges  {len(interlocks):>7,}")
    dated = sum(1 for e in edges if e["year"])
    print(f"  ties carrying a year     {dated:>7,}  ({100 * dated / len(edges):.1f}%)")

    rule("2. Best-connected directors (board seats only)")
    print(f"  {'boards':>6}  {'years':<12} {'name':<30} territories")
    for p in people[:15]:
        yrs = f"{p['first_year']}-{p['last_year']}" if p["first_year"] else "n/a"
        name = (p["name_variants"].split("; ")[0] or p["person_id"])[:29]
        print(f"  {p['n_board_companies']:>6}  {yrs:<12} {name:<30} {p['regions'][:34]}")

    rule("3. Densest company interlocks (shared directors, all years pooled)")
    print("  NOTE: pooled over time. For temporal work use the by-period file.")
    for e in interlocks[:12]:
        print(f"  w={e['weight']:>2}  {e['company_name_1'][:33]:35s} <-> "
              f"{e['company_name_2'][:33]}")

    rule("4. Interlocks within period (the version to use for temporal claims)")
    by_period: dict[str, list[dict]] = defaultdict(list)
    for e in period_il:
        by_period[e["period"]].append(e)
    order = ["pre_1914", "1914_1929", "1930_1944", "1945_1962", "post_1962"]
    for per in order:
        rows = sorted(by_period.get(per, []), key=lambda r: -int(r["weight"]))
        if not rows:
            continue
        top = rows[0]
        names = {f["company_id"]: f["name"] for f in firms}
        print(f"\n  {per}  ({len(rows):,} edges)")
        for e in rows[:3]:
            print(f"     w={e['weight']:>2}  {names.get(e['company_id_1'], '?')[:31]:33s} <-> "
                  f"{names.get(e['company_id_2'], '?')[:31]}")

    rule("5. Temporal distribution of observations")
    per_counts = Counter(e["period"] or "undated" for e in edges)
    total = sum(per_counts.values())
    for per in order + ["undated"]:
        n = per_counts.get(per, 0)
        if not n:
            continue
        bar = "#" * int(46 * n / max(per_counts.values()))
        print(f"  {per:<11} {n:>7,}  {100 * n / total:>4.1f}%  {bar}")

    rule("6. Sectors with the most board ties")
    sector_ties = Counter()
    for a in affil:
        if a["sector"] and a["company_key"]:
            sector_ties[a["sector"]] += 1
    for sec, n in sector_ties.most_common(12):
        print(f"  {n:>6,}  {sec[:66]}")

    rule("7. Territories")
    region_firms = Counter()
    for f in firms:
        for r in f["regions"].split("; "):
            if r:
                region_firms[r] += 1
    for reg, n in region_firms.most_common():
        print(f"  {n:>6,} companies  {reg}")

    rule("8. Corporate directorships (a company sitting on another's board)")
    print("  Direct evidence of control or alliance, distinct from an interlock.")
    for e in corporate[:10]:
        yrs = f"{e['first_year']}-{e['last_year']}" if e["first_year"] else "n/a"
        print(f"  {e['from_name'][:32]:34s} -> {e['to_name'][:28]:30s} {yrs}")

    rule("9. Roles as recorded")
    roles = Counter(a["role"] for a in affil)
    for role, n in roles.most_common():
        print(f"  {n:>7,}  {role}")

    rule("10. Provenance: tracing one tie back to its source")
    # Pick the most-documented board tie and follow it back.
    best = max(affil, key=lambda a: (bool(a["company_key"]), bool(a["source_ref"]),
                                     len(a["source_ref"] or "")))
    doc_by_id = {d["doc_id"]: d for d in docs}
    doc = doc_by_id.get(best["doc_id"], {})
    print(f"  person        {best['name_clean']}")
    print(f"  raw fragment  {best['member_raw']!r}")
    print(f"  role          {best['role']}")
    print(f"  company       {best['company_name']}")
    print(f"  year          {best['year'] or '(undated)'}")
    print(f"  cited source  {best['source_ref'] or '(none)'}")
    print(f"  found via     anchor={best['anchor_type']}, trigger={best['trigger']}, "
          f"name rule={best['parse_note']}")
    print(f"  dossier       {doc.get('title_raw', '?')[:70]}")
    print(f"  PDF           {doc.get('pdf_url', '?')}")
    if best["annotation"]:
        print(f"  compiler note {best['annotation']}")

    rule("11. Quality flags worth checking before you publish")
    res = load("person_resolution.csv")
    amb = sum(1 for r in res if r["ambiguous"] == "1")
    print(f"  person keys left unmerged as ambiguous   {amb:,} of {len(res):,}")
    dupes = load("company_duplicate_candidates.csv")
    print(f"  company duplicate pairs awaiting review  {len(dupes):,}")
    unattributed = sum(1 for a in affil if not a["company_key"])
    print(f"  ties with no company attributed          {unattributed:,} of {len(affil):,} "
          f"({100 * unattributed / len(affil):.1f}%, excluded from the network)")
    spans = [
        int(p["last_year"]) - int(p["first_year"])
        for p in people if p["first_year"] and p["last_year"]
    ]
    print(f"  people with >60y observation span        "
          f"{sum(1 for s in spans if s > 60):,} of {len(spans):,} "
          f"(likely namesakes merged)")
    print("\n  See docs/METHODOLOGY.md §6 for what these mean for inference.")


if __name__ == "__main__":
    main()
