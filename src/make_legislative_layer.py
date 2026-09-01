"""Stage 14 - the legislative layer, and what continuity means here.

    python3 src/make_legislative_layer.py

Three files:

    legislators.csv                  one row per parliamentarian
    edges_legislator_interlock.csv   two parliamentarians, one board
    legislative_continuity.csv       the roster snapshots, as transitions

**What this joins.** Two independent readings of the corpus produce mandates.
`parse_mandates.py` (stage 3g) scrapes every mention of a deputy or senator
anywhere in the 5,863 documents - 2,444 of them - and is broad but shallow: it
knows the chamber, usually the seat, rarely the term. `parse_rosters.py` (stage
3h) reads the compiler's five dated directories of *Parlementaires et
financiers* and is narrow but deep: 1,095 entries, 994 with a seat, 540 with a
term, each stamped with the volume's year. Union the two on the resolved person
key and you have a population; intersect it with the company network and you
have the object of interest, which is the men who sat in the Chamber or the
Senate *and* on a colonial board.

**Continuity is three different things, and they are kept apart.**

1. *Continuity of tenure* - one man's own run, from his first mandate year to
   his last. `first_year`/`last_year`, and the span figures draw on them.
2. *Continuity of presence* - whether the same man is in the compiler's roster
   again five or six years later. This is what `legislative_continuity.csv`
   measures, as `entered` / `stayed` / `left` between consecutive snapshots,
   because a roster is a census and the interesting number is the turnover
   between two of them. 292 of 577 men appear in two or more; 177 in three or
   more.
3. *Continuity of position* - whether a *board* keeps a parliamentarian on it
   across snapshots, which is continuity of the firm's access rather than of
   any individual's career. That is `n_snapshots` on the company side.

Conflating these is the easy mistake. A firm can hold parliamentary access
continuously for thirty years while never keeping the same parliamentarian for
two consecutive volumes, and the reverse also happens.

**Two overlaps, and the difference matters.** Two parliamentarians on one board
may have sat *at the same time* or one after the other. An edge in
`edges_legislator_interlock.csv` therefore carries `mandates_overlap`: 1 where
their known terms intersect, 0 where they do not, and empty where at least one
term is unknown - which is most of them, and is stated rather than assumed. An
analysis that reads every shared board as a live connection will overstate the
network, and one that requires a proven overlap will understate it by the size
of the unknown column.

**The proxy holdings are kept out of the main network and in here.** The
compiler's group title says *interesses directement ou par des proches* - "or
through relatives" - and stage 3h keys those ties to the relative. They are the
prete-nom structure the source exists to document, so they are counted here
(`n_proxy_firms`) and excluded from the interlock graph, where they would
assert a seat the source places one step away.
"""

from __future__ import annotations

import collections
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ensure_dir  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")

SNAPSHOTS = ["1924", "1930", "1932", "1936", "1954"]
MIN_SHARED = 1          # boards two legislators must share to make an edge


def load(name: str) -> list[dict]:
    path = os.path.join(PROC, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def resolver() -> dict[str, str]:
    """Every raw person key mapped to the key the network merged it into."""
    out: dict[str, str] = {}
    for row in load("persons_resolved.csv"):
        pid = row["person_id"]
        out[pid] = pid
        for k in (row.get("merged_keys") or "").split(";"):
            k = k.strip()
            if k:
                out[k] = pid
    return out


def _int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def overlap(a: tuple[int | None, int | None],
            b: tuple[int | None, int | None]) -> str:
    """Whether two mandate spans intersect. "" when either is unknown."""
    if None in a or None in b:
        return ""
    return "1" if a[0] <= b[1] and b[0] <= a[1] else "0"


def main() -> None:
    keys = resolver()
    mentions = load("person_mandates.csv")
    roster = load("roster_mandates.csv")
    ties = load("edges_person_company.csv") or load("affiliations.csv")
    companies = {c["company_id"]: c for c in load("companies.csv")}
    roster_ties = load("affiliations_roster.csv")

    def pid(raw: str) -> str:
        return keys.get(raw, raw)

    # --- one row per parliamentarian ------------------------------------
    people: dict[str, dict] = {}

    def rec(key: str, name: str) -> dict:
        r = people.setdefault(key, {
            "person_id": key, "name_clean": name,
            "chambers": set(), "constituencies": set(), "snapshots": set(),
            "years": [], "sources": set(), "also_minister": "0",
        })
        if len(name) > len(r["name_clean"]):
            r["name_clean"] = name
        return r

    for row in mentions:
        r = rec(pid(row["person_key"]), row["name_clean"])
        r["chambers"].add(row["chamber"])
        if row["constituency"]:
            r["constituencies"].add(row["constituency"])
        for field in ("year_start", "year_end"):
            y = _int(row.get(field))
            if y:
                r["years"].append(y)
        r["sources"].add("mention")
        if row.get("also_minister") == "1":
            r["also_minister"] = "1"

    for row in roster:
        r = rec(pid(row["person_key"]), row["name_clean"])
        r["chambers"].add(row["chamber"])
        if row["constituency"]:
            r["constituencies"].add(row["constituency"])
        if row["snapshot_year"]:
            r["snapshots"].add(row["snapshot_year"])
        for field in ("year_start", "year_end"):
            y = _int(row.get(field))
            if y:
                r["years"].append(y)
        r["sources"].add("roster")

    # --- the company side ------------------------------------------------
    firms_of: dict[str, set[str]] = collections.defaultdict(set)
    for row in ties:
        key = pid(row.get("person_id") or row.get("person_key") or "")
        firm = row.get("company_id") or row.get("company_key") or ""
        if key and firm:
            firms_of[key].add(firm)

    proxy_of: dict[str, set[str]] = collections.defaultdict(set)
    proxy_for: dict[str, set[str]] = collections.defaultdict(set)
    for row in roster_ties:
        if row.get("held_by") != "relative":
            continue
        holder = pid(row["person_key"])
        proxy_of[holder].add(row["company_key"])
        if row.get("related_to"):
            proxy_for[row["related_to"]].add(row["company_key"])

    def territories(firm_keys) -> list[str]:
        out = set()
        for k in firm_keys:
            c = companies.get(k) or {}
            t = ((c.get("countries") or c.get("regions") or "")
                 .split("; ")[0].strip())
            if t:
                out.add(t)
        return sorted(out)

    rows = []
    for key, r in sorted(people.items()):
        firms = firms_of.get(key, set())
        years = sorted(r["years"])
        rows.append({
            "person_id": key,
            "name_clean": r["name_clean"],
            "chambers": "; ".join(sorted(r["chambers"])),
            "both_chambers": "1" if len(r["chambers"]) > 1 else "0",
            "constituencies": "; ".join(sorted(r["constituencies"])),
            "n_constituencies": len(r["constituencies"]),
            "also_minister": r["also_minister"],
            "first_year": years[0] if years else "",
            "last_year": years[-1] if years else "",
            "tenure_years": (years[-1] - years[0]) if len(years) > 1 else "",
            "n_snapshots": len(r["snapshots"]),
            "snapshots": "; ".join(sorted(r["snapshots"])),
            # A key with no forename attested is a surname bucket, not a man:
            # `paris` collects every Paris in a 34,500-person network, and its
            # 34 companies belong to several people. The mandate is still
            # real - the corpus does name a senator by surname alone - so the
            # row stays, flagged, and every company-side figure drops it.
            "key_ambiguous": "1" if len(r["name_clean"].split()) < 2 else "0",
            "in_network": "1" if firms else "0",
            "n_companies": len(firms),
            "n_proxy_firms": len(proxy_of.get(key, set()))
            + len(proxy_for.get(r["name_clean"], set())),
            "territories": "; ".join(territories(firms)),
            "n_territories": len(territories(firms)),
            "evidence": "; ".join(sorted(r["sources"])),
        })

    write("legislators.csv", rows)

    # --- legislator-legislator interlocks --------------------------------
    inside = {r["person_id"]: r for r in rows
              if r["in_network"] == "1" and r["key_ambiguous"] == "0"}
    by_firm: dict[str, list[str]] = collections.defaultdict(list)
    for key in inside:
        for firm in sorted(firms_of[key]):
            by_firm[firm].append(key)

    shared: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for firm, members in sorted(by_firm.items()):
        members = sorted(set(members))
        if len(members) < 2 or len(members) > 60:
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                shared[(a, b)].add(firm)

    edges = []
    for (a, b), firms in sorted(shared.items()):
        if len(firms) < MIN_SHARED:
            continue
        ra, rb = inside[a], inside[b]
        span_a = (_int(ra["first_year"]), _int(ra["last_year"]))
        span_b = (_int(rb["first_year"]), _int(rb["last_year"]))
        names = sorted(companies.get(f, {}).get("name") or f
                       for f in firms)
        edges.append({
            "source": a, "target": b,
            "source_name": ra["name_clean"], "target_name": rb["name_clean"],
            "weight": len(firms),
            "shared_companies": "; ".join(names[:8]),
            "source_chamber": ra["chambers"], "target_chamber": rb["chambers"],
            "same_chamber": "1" if ra["chambers"] == rb["chambers"] else "0",
            "mandates_overlap": overlap(span_a, span_b),
        })
    edges.sort(key=lambda e: (-e["weight"], e["source"], e["target"]))
    write("edges_legislator_interlock.csv", edges)

    # --- roster continuity, snapshot to snapshot ------------------------
    present: dict[str, set[str]] = collections.defaultdict(set)
    for row in roster:
        if row["snapshot_year"] in SNAPSHOTS:
            present[row["snapshot_year"]].add(pid(row["person_key"]))
    trans = []
    for i, year in enumerate(SNAPSHOTS):
        prev = present[SNAPSHOTS[i - 1]] if i else set()
        now = present[year]
        seen_before = set().union(*(present[y] for y in SNAPSHOTS[:i])) \
            if i else set()
        trans.append({
            "snapshot_year": year,
            "n_present": len(now),
            "n_entered": len(now - seen_before),
            "n_stayed": len(now & prev),
            "n_returned": len(now & seen_before - prev),
            "n_left": len(prev - now),
            "carryover_rate": (f"{len(now & prev) / len(prev):.3f}"
                              if prev else ""),
        })
    write("legislative_continuity.csv", trans)

    both = sum(1 for r in rows if r["both_chambers"] == "1")
    net = [r for r in rows if r["in_network"] == "1"]
    print(f"legislators: {len(rows):,} named, {len(net):,} on a colonial "
          f"board, {both:,} sat in both chambers", file=sys.stderr)
    print(f"interlocks: {len(edges):,} pairs; "
          f"{sum(1 for e in edges if e['mandates_overlap'] == '1'):,} with "
          f"overlapping terms, "
          f"{sum(1 for e in edges if e['mandates_overlap'] == ''):,} unknown",
          file=sys.stderr)
    for t in trans:
        print(f"  {t['snapshot_year']}  present {t['n_present']:4}  "
              f"entered {t['n_entered']:4}  stayed {t['n_stayed']:4}  "
              f"left {t['n_left']:4}  carryover {t['carryover_rate'] or '-'}",
              file=sys.stderr)


def write(name: str, rows: list[dict]) -> None:
    ensure_dir(PROC)
    path = os.path.join(PROC, name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows
                           else ["empty"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {os.path.relpath(path, ROOT)}: {len(rows):,} rows",
          file=sys.stderr)


if __name__ == "__main__":
    main()
