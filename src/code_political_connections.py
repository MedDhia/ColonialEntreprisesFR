"""Stage 16 - code each company by its political connection.

    python3 src/code_political_connections.py
    python3 src/code_political_connections.py --review 30   # print an audit set

Writes `company_political.csv` (one row per firm with a board),
`political_connections_by_territory.csv`, and
`political_connections_review.csv`.

**Read `data/reference/political_connection_rules.md` before using the
variable.** It states the definition, the tier ordering and why it is an
assumption, the offices that were rejected and why, and the four things the
coding cannot do. This module is the implementation; that file is the argument.

The short version. A firm is politically connected when someone holding a board
seat in it is attested holding an office of state. Five classes, in the order
that sets `connection_tier`:

    executive       minister, head of state, governor-general, resident
    legislature     deputy, senator
    administration  colonial administrator, conseiller d'Etat, prefect, consul
    local           conseiller general, mayor
    proxy           a named relative of a parliamentarian

Three columns exist because the obvious single number would be wrong:

- **`has_sitting` against `has_former`.** A sitting deputy on a board is a
  conflict of interest; a retired governor-general is a revolving door. They
  are never summed. `former` comes from the source's own `ancien` / `honoraire`,
  so `n_former` is a floor and `n_sitting` a ceiling.
- **`n_concurrent` and `n_testable`.** Most director-firm pairs cannot be tested
  for simultaneity because one of the two years is missing. Reporting
  `n_concurrent` without `n_testable` beside it would read as a corrected count
  when it is a much smaller, better-evidenced subset.
- **`n_connected_neighbours`, deliberately outside the tier.** One interlock
  step from a minister's board is a different construct from having a minister
  on yours, and folding it in would let the variable inflate with the network.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sectors  # noqa: E402
from build_network import BOARD_ROLES, read_csv, write_csv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")

# Office class -> connection class. The mapping is the argued part; see the
# rules file. `state_bank` sits in `administration` because a governorship of
# the Banque de France is a state appointment without being a colonial one.
OFFICE_TO_CLASS = {
    "head_of_state": "executive",
    "minister": "executive",
    "colonial_governor": "executive",
    "colonial_admin": "administration",
    "senior_state": "administration",
    "state_bank": "administration",
    "colonial_council": "administration",
    "local_elected": "local",
}

CLASSES = ["executive", "legislature", "administration", "local", "proxy"]

# Tier is set by the highest class attested on the board.
TIER = {"executive": 4, "legislature": 3, "administration": 2,
        "local": 1, "proxy": 1}
TIER_NAME = {4: "executive", 3: "legislature", 2: "administration",
             1: "local_or_proxy", 0: "none"}


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolver() -> dict[str, str]:
    """Raw person key -> the key the network merged it into."""
    out: dict[str, str] = {}
    for row in read_csv("persons_resolved.csv"):
        pid = row["person_id"]
        out[pid] = pid
        for k in (row.get("merged_keys") or "").split(";"):
            k = k.strip()
            if k:
                out[k] = pid
    return out


class Person:
    """What is known about one person's offices, pooled across mentions."""

    __slots__ = ("classes", "sitting", "former", "spans", "n_mentions",
                 "roster", "footnote_only", "ambiguous", "name")

    def __init__(self, name=""):
        self.classes: set[str] = set()
        self.sitting: set[str] = set()
        self.former: set[str] = set()
        self.spans: list[tuple[int, int]] = []
        self.n_mentions = 0
        self.roster = False
        self.footnote_only = True
        self.ambiguous = False
        self.name = name

    def add(self, klass, former, pattern, span=None, roster=False):
        self.classes.add(klass)
        (self.former if former else self.sitting).add(klass)
        self.n_mentions += 1
        if span:
            self.spans.append(span)
        if roster:
            self.roster = True
        if pattern != "entry_header":
            self.footnote_only = False

    def confidence(self) -> str:
        if self.ambiguous or (self.footnote_only and not self.roster):
            return "low"
        if self.roster or self.n_mentions >= 2:
            return "high"
        return "medium"


def build_people(keys) -> dict[str, Person]:
    """Every politically connected person, keyed by resolved person id."""
    people: dict[str, Person] = {}

    def rec(raw, name):
        pid = keys.get(raw, raw)
        p = people.setdefault(pid, Person(name))
        if len(name) > len(p.name):
            p.name = name
        if len(name.split()) < 2:
            p.ambiguous = True
        return p

    for row in read_csv("person_mandates.csv"):
        p = rec(row["person_key"], row["name_clean"])
        span = (_int(row["year_start"]), _int(row["year_end"]))
        p.add("legislature", row.get("former") == "1", row["pattern"],
              span if None not in span else None)
        if row.get("also_minister") == "1":
            p.add("executive", False, row["pattern"])

    for row in read_csv("roster_mandates.csv"):
        p = rec(row["person_key"], row["name_clean"])
        span = (_int(row["year_start"]), _int(row["year_end"]))
        p.add("legislature", False, "roster",
              span if None not in span else None, roster=True)

    for row in read_csv("person_offices.csv"):
        klass = OFFICE_TO_CLASS.get(row["office_class"])
        if not klass:
            continue
        p = rec(row["person_key"], row["name_clean"])
        p.add(klass, row["former"] == "1", row["pattern"])

    # The compiler's own genealogy: a director who is a named relative of a
    # named parliamentarian. `person_key` on those rows is the relative's.
    for row in read_csv("affiliations_roster.csv"):
        if row.get("held_by") != "relative":
            continue
        p = rec(row["person_key"], row["name_clean"])
        p.add("proxy", False, "roster", roster=True)

    return people


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", type=int, default=0,
                    help="print this many rows for hand-checking")
    args = ap.parse_args()

    keys = resolver()
    people = build_people(keys)
    companies = {c["company_id"]: c for c in read_csv("companies.csv")}
    sector_map = sectors.load_map()

    # Board seats only: a firm mentioned in a director's biography is not a
    # firm he sat on, and `is_board_seat` is what draws that line.
    board: dict[str, set[str]] = collections.defaultdict(set)
    tie_years: dict[tuple[str, str], set[int]] = collections.defaultdict(set)
    for row in read_csv("edges_person_company.csv"):
        if row.get("is_board_seat") != "1" and row.get("role") not in BOARD_ROLES:
            continue
        firm, person = row["company_id"], row["person_id"]
        if not firm or not person:
            continue
        board[firm].add(person)
        y = _int(row.get("year"))
        if y:
            tie_years[(firm, person)].add(y)

    # One interlock hop, for the indirect measure. Built from the board sets
    # rather than read from the interlock edge file, so the neighbourhood is
    # exactly "shares a board member with", on the same rows as everything else.
    firms_of: dict[str, set[str]] = collections.defaultdict(set)
    for firm, members in board.items():
        for person in members:
            firms_of[person].add(firm)

    _sector_cache: dict[str, tuple[str, str, str]] = {}

    def sector_of(rec):
        key = rec.get("company_id", "")
        if key not in _sector_cache:
            _sector_cache[key] = sectors.sector_of(rec, sector_map)
        return _sector_cache[key]

    rows = []
    for firm in sorted(board):
        members = board[firm]
        rec = companies.get(firm, {})
        connected = {p: people[p] for p in members if p in people}
        counts = collections.Counter()
        sitting = collections.Counter()
        former = collections.Counter()
        for pid, p in connected.items():
            for klass in p.classes:
                counts[klass] += 1
            for klass in p.sitting:
                sitting[klass] += 1
            for klass in p.former:
                former[klass] += 1

        # Concurrency, on the pairs where both years are known.
        testable = concurrent = 0
        for pid, p in connected.items():
            years = tie_years.get((firm, pid)) or set()
            if not years or not p.spans:
                continue
            testable += 1
            if any(a <= y <= b for y in years for a, b in p.spans):
                concurrent += 1

        neighbours = set()
        for pid in members:
            neighbours |= firms_of[pid]
        neighbours.discard(firm)
        n_conn_nb = sum(1 for f in neighbours
                        if any(p in people for p in board[f]))

        tier = max((TIER[k] for k in counts), default=0)
        confidences = [p.confidence() for p in connected.values()]
        conf = ("high" if "high" in confidences else
                "medium" if "medium" in confidences else
                "low" if confidences else "")
        years_seen = {y for pid in connected
                      for y in tie_years.get((firm, pid), set())}

        rows.append({
            "company_id": firm,
            "name": rec.get("name", firm),
            # First listed, which is the convention the rest of the
            # pipeline uses (`make_figures.territory_of`). For a transversal
            # firm it is arbitrary, so `n_territories` and `all_territories`
            # sit beside it rather than letting one label stand for eight.
            "territory": (rec.get("countries") or "").split("; ")[0],
            "n_territories": len([t for t in (rec.get("countries") or "")
                                  .split("; ") if t]),
            "all_territories": rec.get("countries", ""),
            # `sector` keeps the raw first-listed label for continuity with
            # the rest of the pipeline. `sector_group` is the analysable one:
            # the first label that is not a filing category, mapped through
            # data/reference/sector_groups.csv. See METHODOLOGY §5l.
            "sector": (rec.get("sectors") or "").split("; ")[0],
            "sector_group": sector_of(rec)[0],
            "sector_group_en": sector_of(rec)[1],
            "sector_raw": sector_of(rec)[2],
            "n_directors": len(members),
            "n_connected": len(connected),
            "share_connected": (f"{len(connected) / len(members):.4f}"
                                if members else ""),
            "connection_tier": tier,
            "connection_tier_name": TIER_NAME[tier],
            **{f"has_{k}": ("1" if counts[k] else "0") for k in CLASSES},
            **{f"n_{k}": counts[k] for k in CLASSES},
            "has_sitting": "1" if sum(sitting.values()) else "0",
            "has_former": "1" if sum(former.values()) else "0",
            "n_sitting": sum(sitting.values()),
            "n_former": sum(former.values()),
            "n_testable": testable,
            "n_concurrent": concurrent,
            "n_connected_neighbours": n_conn_nb,
            "indirect_only": "1" if not connected and n_conn_nb else "0",
            "first_connection_year": min(years_seen) if years_seen else "",
            "last_connection_year": max(years_seen) if years_seen else "",
            "confidence": conf,
            "connected_directors": "; ".join(
                sorted(p.name for p in connected.values())[:8]),
        })

    write_csv("company_political.csv", rows, list(rows[0].keys()) if rows
              else ["company_id"])

    # --- the board-size null ---------------------------------------------
    # Share of firms with a connected director is partly a board-size
    # artefact: a board of ten has ten chances to contain one, a board of two
    # has two. Finance's median board is 10 and metallurgy's is 2, so the raw
    # shares are not comparable as they stand.
    #
    # The benchmark is the simplest defensible one. Let p be the corpus-wide
    # seat-level rate — connected director-seats over all director-seats.
    # Under a null where each seat is independently connected with
    # probability p, a firm with k directors has probability 1 - (1 - p)^k of
    # holding at least one, and a sector's expected share is the mean of that
    # over its firms. `excess_share` is observed minus expected: it is the part
    # of a sector's connection that its board sizes do not already predict.
    #
    # The null is deliberately crude. It assumes seats are exchangeable, which
    # they are not, and it ignores that a firm's directors are correlated with
    # each other. It is a yardstick for reading the raw shares, not a model.
    total_seats = sum(int(r["n_directors"]) for r in rows)
    total_conn_seats = sum(int(r["n_connected"]) for r in rows)
    seat_rate = (total_conn_seats / total_seats) if total_seats else 0.0

    def expected_share(group) -> float:
        if not group:
            return 0.0
        return sum(1.0 - (1.0 - seat_rate) ** int(x["n_directors"])
                   for x in group) / len(group)

    # --- by territory ----------------------------------------------------
    by_terr: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_terr[r["territory"] or "(unlabelled)"].append(r)
    summary = []
    for terr, group in sorted(by_terr.items(),
                              key=lambda kv: -len(kv[1])):
        n = len(group)
        conn = [g for g in group if int(g["connection_tier"]) > 0]
        summary.append({
            "territory": terr,
            "n_firms": n,
            "n_connected": len(conn),
            "share_connected": f"{len(conn) / n:.4f}",
            **{f"n_tier_{t}": sum(1 for g in group
                                  if int(g["connection_tier"]) == t)
               for t in (4, 3, 2, 1, 0)},
            "n_sitting": sum(1 for g in group if g["has_sitting"] == "1"),
            "n_former": sum(1 for g in group if g["has_former"] == "1"),
            "n_indirect_only": sum(1 for g in group
                                   if g["indirect_only"] == "1"),
            "mean_share_connected": (
                f"{sum(float(g['share_connected'] or 0) for g in group) / n:.4f}"),
            "n_seats": sum(int(g["n_directors"]) for g in group),
            "expected_share_connected": f"{expected_share(group):.4f}",
            "excess_share": (
                f"{len(conn) / n - expected_share(group):+.4f}"),
        })
    write_csv("political_connections_by_territory.csv", summary,
              list(summary[0].keys()) if summary else ["territory"])

    # --- by sector -------------------------------------------------------
    # Firms whose only sector label is a filing category carry no sector, and
    # are reported as their own row rather than dropped without trace: they are
    # 46% of the coded firms and their absence is the first thing a reader of
    # this table needs to know.
    by_sec: dict[str, list[dict]] = collections.defaultdict(list)
    english: dict[str, str] = {}
    for r in rows:
        by_sec[r["sector_group"]].append(r)
        english[r["sector_group"]] = r["sector_group_en"]
    sec_summary = []
    for group, g in sorted(by_sec.items(), key=lambda kv: -len(kv[1])):
        n = len(g)
        conn = [x for x in g if int(x["connection_tier"]) > 0]
        sec_summary.append({
            "sector_group": group,
            "sector_group_en": english.get(group, group),
            "n_firms": n,
            "n_connected": len(conn),
            "share_connected": f"{len(conn) / n:.4f}",
            **{f"n_tier_{t}": sum(1 for x in g
                                  if int(x["connection_tier"]) == t)
               for t in (4, 3, 2, 1, 0)},
            **{f"share_tier_{t}": f"{sum(1 for x in g if int(x['connection_tier']) == t) / n:.4f}"
               for t in (4, 3, 2, 1, 0)},
            **{f"n_{k}": sum(1 for x in g if x[f"has_{k}"] == "1")
               for k in CLASSES},
            "n_sitting": sum(1 for x in g if x["has_sitting"] == "1"),
            "n_former": sum(1 for x in g if x["has_former"] == "1"),
            "n_indirect_only": sum(1 for x in g if x["indirect_only"] == "1"),
            "mean_share_connected": (
                f"{sum(float(x['share_connected'] or 0) for x in g) / n:.4f}"),
            "median_board_size": sorted(int(x["n_directors"]) for x in g)[n // 2],
            "n_seats": sum(int(x["n_directors"]) for x in g),
            "director_rate": (
                f"{sum(int(x['n_connected']) for x in g) / max(sum(int(x['n_directors']) for x in g), 1):.4f}"),
            "expected_share_connected": f"{expected_share(g):.4f}",
            "excess_share": (
                f"{len(conn) / n - expected_share(g):+.4f}"),
        })
    write_csv("political_connections_by_sector.csv", sec_summary,
              list(sec_summary[0].keys()) if sec_summary else ["sector_group"])

    # --- the review set --------------------------------------------------
    review = sorted((r for r in rows if int(r["connection_tier"]) > 0),
                    key=lambda r: (-int(r["connection_tier"]),
                                   -int(r["n_connected"]), r["company_id"]))
    write_csv("political_connections_review.csv", review[:400],
              ["company_id", "name", "territory", "connection_tier_name",
               "n_directors", "n_connected", "share_connected",
               "has_sitting", "has_former", "n_testable", "n_concurrent",
               "confidence", "connected_directors"])

    tiers = collections.Counter(int(r["connection_tier"]) for r in rows)
    print(f"companies with a board: {len(rows):,}", file=sys.stderr)
    for t in (4, 3, 2, 1, 0):
        print(f"  tier {t} {TIER_NAME[t]:<15} {tiers[t]:6,}"
              f"  {tiers[t] / len(rows):6.1%}", file=sys.stderr)
    conn = [r for r in rows if int(r["connection_tier"]) > 0]
    print(f"connected firms: {len(conn):,} ({len(conn) / len(rows):.1%})",
          file=sys.stderr)
    print(f"  with a sitting office-holder: "
          f"{sum(1 for r in conn if r['has_sitting'] == '1'):,}; "
          f"a former one: {sum(1 for r in conn if r['has_former'] == '1'):,}",
          file=sys.stderr)
    print(f"  concurrency testable on "
          f"{sum(int(r['n_testable']) for r in rows):,} director-firm pairs, "
          f"concurrent on {sum(int(r['n_concurrent']) for r in rows):,}",
          file=sys.stderr)
    print(f"  indirect only: "
          f"{sum(1 for r in rows if r['indirect_only'] == '1'):,}",
          file=sys.stderr)
    coded = [r for r in rows if r["sector_group"] != "not_a_sector"]
    print(f"  with an economic sector: {len(coded):,} "
          f"({len(coded) / len(rows):.1%}); the rest carry only a filing "
          f"category", file=sys.stderr)
    print(f"  confidence: "
          f"{collections.Counter(r['confidence'] for r in conn).most_common()}",
          file=sys.stderr)

    if args.review:
        for r in review[:args.review]:
            print(f"\n{r['name'][:64]}  [{r['territory'] or '-'}]"
                  f"\n   tier {r['connection_tier']} "
                  f"{r['connection_tier_name']}, {r['n_connected']}/"
                  f"{r['n_directors']} directors, conf {r['confidence']}"
                  f", sitting={r['has_sitting']} former={r['has_former']}"
                  f"\n   {r['connected_directors']}")


if __name__ == "__main__":
    main()
