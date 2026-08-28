"""Stage 5 - split the dataset into per-territory bundles.

Each bundle is a **self-contained network** for one territory: its documents,
its observed ties, and the nodes, edges and projections computed from just
those ties, plus a GraphML of its company interlocks.

Two granularities are written, because the useful unit differs by question:

    data/by_country/<slug>/   62 territories as the source labels them
                             (Madagascar, Senegal, Cote d'Ivoire, Syrie-Liban…)
    data/by_region/<slug>/    13 index-page groupings
                             (Afrique occidentale francaise, Indochine…)

Three decisions worth knowing, all of them consequential:

1. **Ties partition; nodes do not.** Every tie carries exactly one territory
   (inherited from the document it was read in), so the bundles' tie counts sum
   to the dataset total. Firms and people, however, appear in every bundle
   where they are observed: 21.3% of people and 9.4% of firms are in more than
   one country bundle, so node counts must *not* be added across bundles. That
   is the right shape for analysis - each bundle is a usable standalone network
   - and the overlap is itself informative, so `territory_manifest.csv` reports
   per-territory how many of its people and firms are shared with another
   territory.

2. **Person identifiers are resolved globally, once, over the whole dataset,
   then applied to each slice.** Resolving within each slice would give the
   same individual a different id in Morocco and in Indochina, which would
   silently destroy exactly the transcolonial careers this dataset is for.
   The ids are *read* from `person_resolution.csv` rather than recomputed, so
   they are stage 4's own decisions and cannot drift from the top-level files.

3. **`Empire (transversal)` is not a country.** It is the source's grouping for
   firms and groups operating across several colonies, and it is the largest
   single bucket. It is kept as its own bundle under an explicit slug so it is
   never mistaken for a territory.

Usage
    python3 src/split_by_country.py
    python3 src/split_by_country.py --min-ties 50   # skip very thin slices
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_network import (  # noqa: E402
    BOARD_ROLES,
    period_of,
    read_csv,
    person_id_for,
    write_graphml,
)
from common import ensure_dir, slugify  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC_DIR = os.path.join(ROOT, "data", "processed")

# The source has no country heading for these pages; the page grouping is the
# most specific label available.
BLANK_COUNTRY_LABEL = "Empire (transversal)"


def slug_for(label: str) -> str:
    return slugify(label, 60)


def territory_of(row: dict, level: str) -> str:
    """The territory a row belongs to, at the requested granularity."""
    if level == "region":
        return row.get("region", "") or BLANK_COUNTRY_LABEL
    return row.get("country", "") or row.get("region", "") or BLANK_COUNTRY_LABEL


def write_slice(path: str, name: str, rows: list[dict], fields: list[str]) -> None:
    ensure_dir(path)
    with open(os.path.join(path, name), "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def build_bundle(
    out_dir: str,
    territory: str,
    docs: list[dict],
    affil: list[dict],
    org_affil: list[dict],
    attrs: list[dict],
    company_names: dict[str, str],
) -> dict:
    """Write one territory's bundle and return its summary row."""
    ensure_dir(out_dir)

    # --- nodes -----------------------------------------------------------
    people: dict[str, dict] = {}
    firms: dict[str, dict] = {}
    for r in affil:
        p = people.setdefault(
            r["person_id"],
            {"person_id": r["person_id"], "surname": r["surname"], "names": set(),
             "companies": set(), "board_companies": set(), "roles": Counter(),
             "years": [], "sectors": set()},
        )
        p["names"].add(r["name_clean"])
        p["companies"].add(r["company_key"])
        if r["is_board_seat"]:
            p["board_companies"].add(r["company_key"])
        p["roles"][r["role"]] += 1
        if r["year"].isdigit():
            p["years"].append(int(r["year"]))
        if r["sector"]:
            p["sectors"].add(r["sector"])

        f = firms.setdefault(
            r["company_key"],
            {"company_id": r["company_key"], "name": company_names.get(r["company_key"], r["company_name"]),
             "sectors": set(), "directors": set(), "years": [], "n_ties": 0},
        )
        f["n_ties"] += 1
        if r["sector"]:
            f["sectors"].add(r["sector"])
        if r["is_board_seat"]:
            f["directors"].add(r["person_id"])
        if r["year"].isdigit():
            f["years"].append(int(r["year"]))

    person_rows = sorted(
        (
            {
                "person_id": p["person_id"],
                "surname": p["surname"],
                "name_variants": "; ".join(sorted(p["names"])),
                "n_companies": len(p["companies"]),
                "n_board_companies": len(p["board_companies"]),
                "n_observations": sum(p["roles"].values()),
                "top_role": p["roles"].most_common(1)[0][0] if p["roles"] else "",
                "first_year": min(p["years"]) if p["years"] else "",
                "last_year": max(p["years"]) if p["years"] else "",
                "sectors": "; ".join(sorted(p["sectors"])),
            }
            for p in people.values()
        ),
        key=lambda r: (-r["n_board_companies"], -r["n_observations"]),
    )
    firm_rows = sorted(
        (
            {
                "company_id": f["company_id"],
                "name": f["name"],
                "sectors": "; ".join(sorted(f["sectors"])),
                "n_ties": f["n_ties"],
                "n_directors": len(f["directors"]),
                "first_year": min(f["years"]) if f["years"] else "",
                "last_year": max(f["years"]) if f["years"] else "",
            }
            for f in firms.values()
        ),
        key=lambda r: (-r["n_directors"], -r["n_ties"]),
    )

    # --- two-mode edges ---------------------------------------------------
    collapsed: dict[tuple, dict] = {}
    for r in affil:
        k = (r["person_id"], r["company_key"])
        e = collapsed.setdefault(
            k,
            {"person_id": r["person_id"], "company_id": r["company_key"],
             "n_observations": 0, "years": [], "roles": Counter(), "board_seat": 0},
        )
        e["n_observations"] += 1
        if r["year"].isdigit():
            e["years"].append(int(r["year"]))
        e["roles"][r["role"]] += 1
        e["board_seat"] = max(e["board_seat"], r["is_board_seat"])
    edge_rows = sorted(
        (
            {
                "person_id": e["person_id"],
                "company_id": e["company_id"],
                "n_observations": e["n_observations"],
                "first_year": min(e["years"]) if e["years"] else "",
                "last_year": max(e["years"]) if e["years"] else "",
                "top_role": e["roles"].most_common(1)[0][0],
                "is_board_seat": e["board_seat"],
            }
            for e in collapsed.values()
        ),
        key=lambda r: (r["company_id"], r["person_id"]),
    )

    # --- interlocks, overall and within period ---------------------------
    seats_by_person: dict[str, set[str]] = defaultdict(set)
    seats_by_person_period: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in affil:
        if not r["is_board_seat"]:
            continue
        seats_by_person[r["person_id"]].add(r["company_key"])
        per = period_of(r["year"])
        if per:
            seats_by_person_period[(r["person_id"], per)].add(r["company_key"])

    def pairs(mapping: dict) -> dict[tuple, set[str]]:
        out: dict[tuple, set[str]] = defaultdict(set)
        for key, comps in mapping.items():
            person = key[0] if isinstance(key, tuple) else key
            tail = (key[1],) if isinstance(key, tuple) else ()
            cs = sorted(comps)
            for i in range(len(cs)):
                for j in range(i + 1, len(cs)):
                    out[(cs[i], cs[j]) + tail].add(person)
        return out

    il = pairs(seats_by_person)
    il_rows = sorted(
        (
            {
                "company_id_1": a,
                "company_id_2": b,
                "company_name_1": company_names.get(a, ""),
                "company_name_2": company_names.get(b, ""),
                "weight": len(ps),
                "shared_directors": "; ".join(sorted(ps))[:400],
            }
            for (a, b), ps in il.items()
        ),
        key=lambda r: -r["weight"],
    )
    ilp = pairs(seats_by_person_period)
    ilp_rows = sorted(
        (
            {"company_id_1": a, "company_id_2": b, "period": per, "weight": len(ps),
             "shared_directors": "; ".join(sorted(ps))[:300]}
            for (a, b, per), ps in ilp.items()
        ),
        key=lambda r: (r["period"], -r["weight"]),
    )

    # --- write ------------------------------------------------------------
    write_slice(out_dir, "documents.csv", docs,
                ["doc_id", "pdf_url", "entry_type", "name_normalised", "sector",
                 "country", "region", "year_start", "year_end", "title_raw"])
    write_slice(out_dir, "affiliations.csv", affil,
                ["doc_id", "company_key", "company_name", "person_id", "name_clean",
                 "surname", "given", "role", "year", "period", "is_board_seat",
                 "source_ref", "annotation", "sector", "country", "region",
                 "anchor_type", "trigger", "member_raw"])
    write_slice(out_dir, "org_affiliations.csv", org_affil,
                ["doc_id", "company_key", "company_name", "member_key", "name_clean",
                 "role", "year", "source_ref", "sector", "country", "region"])
    write_slice(out_dir, "company_attributes.csv", attrs,
                ["company_key", "company_name", "attribute", "value", "year",
                 "source_ref", "doc_id"])
    write_slice(out_dir, "persons.csv", person_rows,
                ["person_id", "surname", "name_variants", "n_companies",
                 "n_board_companies", "n_observations", "top_role", "first_year",
                 "last_year", "sectors"])
    write_slice(out_dir, "companies.csv", firm_rows,
                ["company_id", "name", "sectors", "n_ties", "n_directors",
                 "first_year", "last_year"])
    write_slice(out_dir, "edges_person_company.csv", edge_rows,
                ["person_id", "company_id", "n_observations", "first_year",
                 "last_year", "top_role", "is_board_seat"])
    write_slice(out_dir, "edges_company_interlock.csv", il_rows,
                ["company_id_1", "company_id_2", "company_name_1", "company_name_2",
                 "weight", "shared_directors"])
    write_slice(out_dir, "edges_company_interlock_by_period.csv", ilp_rows,
                ["company_id_1", "company_id_2", "period", "weight", "shared_directors"])

    if il_rows:
        ids = sorted({e["company_id_1"] for e in il_rows} | {e["company_id_2"] for e in il_rows})
        by_id = {f["company_id"]: f for f in firm_rows}
        nodes = [
            (cid, {
                "label": by_id.get(cid, {}).get("name", cid),
                "sectors": by_id.get(cid, {}).get("sectors", ""),
                "n_directors": by_id.get(cid, {}).get("n_directors", 0),
                "territory": territory,
            })
            for cid in ids
        ]
        edges = [(e["company_id_1"], e["company_id_2"], {"weight": e["weight"]}) for e in il_rows]
        write_graphml(os.path.join(out_dir, "company_interlock.graphml"), nodes, edges)

    years = [int(r["year"]) for r in affil if r["year"].isdigit()]
    return {
        "_person_ids": set(people),
        "_company_ids": set(firms),
        "territory": territory,
        "slug": os.path.basename(out_dir),
        "n_documents": len(docs),
        "n_ties": len(affil),
        "n_board_ties": sum(1 for r in affil if r["is_board_seat"]),
        "n_persons": len(person_rows),
        "n_companies": len(firm_rows),
        "n_two_mode_edges": len(edge_rows),
        "n_interlock_edges": len(il_rows),
        "n_corporate_ties": len(org_affil),
        "first_year": min(years) if years else "",
        "last_year": max(years) if years else "",
    }


def run_level(level: str, min_ties: int) -> list[dict]:
    """Build every bundle at one granularity. Returns manifest rows."""
    out_root = os.path.join(ROOT, "data", f"by_{level}")
    ensure_dir(out_root)

    documents = read_csv("documents.csv")
    affiliations = read_csv("affiliations.csv")
    org_affil = read_csv("org_affiliations.csv")
    attributes = read_csv("company_attributes.csv")
    companies = read_csv("companies.csv")
    company_names = {c["company_id"]: c["name"] for c in companies}

    # Person ids come from stage 4's crosswalk rather than being recomputed
    # here. Recomputing looked equivalent and was not: this stage sees only
    # `affiliations.csv`, while stage 4 resolves over all five genres, so the
    # two ran on different key populations and could disagree about a fold or a
    # split. The bundles promise ids that match the top-level files, so they
    # have to be stage 4's ids.
    res = read_csv("person_resolution.csv")
    if not res:
        raise SystemExit("person_resolution.csv missing - run src/build_network.py first")
    mapping = {r["person_key"]: r["person_key_resolved"] for r in res}
    splits: dict[str, set] = {}
    for r in res:
        if r.get("split_forenames"):
            splits[r["person_key_resolved"]] = set(r["split_forenames"].split("; "))

    usable = [r for r in affiliations if r["company_key"] and r["person_key"]]
    for r in usable:
        r["person_id"] = person_id_for(r, mapping, splits)
        r["period"] = period_of(r["year"])
        r["is_board_seat"] = 1 if r["role"] in BOARD_ROLES else 0

    attrs_by_doc: dict[str, list[dict]] = defaultdict(list)
    for a in attributes:
        attrs_by_doc[a["doc_id"]].append(a)

    groups: dict[str, dict[str, list]] = defaultdict(
        lambda: {"docs": [], "affil": [], "org": [], "attrs": []}
    )
    for d in documents:
        groups[territory_of(d, level)]["docs"].append(d)
    for r in usable:
        groups[territory_of(r, level)]["affil"].append(r)
    for r in org_affil:
        if r["company_key"] and r["member_key"]:
            groups[territory_of(r, level)]["org"].append(r)
    for d in documents:
        t = territory_of(d, level)
        groups[t]["attrs"].extend(attrs_by_doc.get(d["doc_id"], ()))

    manifest: list[dict] = []
    skipped: list[tuple[str, int]] = []
    for territory, g in sorted(groups.items(), key=lambda kv: -len(kv[1]["affil"])):
        if len(g["affil"]) < min_ties:
            skipped.append((territory, len(g["affil"])))
            continue
        out_dir = os.path.join(out_root, slug_for(territory))
        manifest.append(
            build_bundle(out_dir, territory, g["docs"], g["affil"], g["org"],
                         g["attrs"], company_names)
        )

    # How much of each territory's elite is also active elsewhere. Computed
    # after every bundle exists, since it is a property of the whole split.
    person_bundles: Counter = Counter()
    company_bundles: Counter = Counter()
    for r in manifest:
        person_bundles.update(r["_person_ids"])
        company_bundles.update(r["_company_ids"])
    for r in manifest:
        shared_p = sum(1 for x in r["_person_ids"] if person_bundles[x] > 1)
        shared_c = sum(1 for x in r["_company_ids"] if company_bundles[x] > 1)
        r["n_persons_shared"] = shared_p
        r["n_companies_shared"] = shared_c
        r["share_persons_shared"] = round(shared_p / len(r["_person_ids"]), 3) if r["_person_ids"] else ""
        r["share_companies_shared"] = round(shared_c / len(r["_company_ids"]), 3) if r["_company_ids"] else ""
        del r["_person_ids"], r["_company_ids"]

    path = os.path.join(out_root, "territory_manifest.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fields = list(manifest[0].keys()) if manifest else ["territory"]
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in manifest:
            w.writerow(r)

    total_ties = len(usable)
    summed = sum(r["n_ties"] for r in manifest)
    print(f"\n{level}: {len(manifest)} bundles in data/by_{level}/", file=sys.stderr)
    if skipped:
        # Never let a threshold drop data silently.
        print(f"  skipped {len(skipped)} below --min-ties "
              f"({sum(n for _, n in skipped)} ties): "
              f"{', '.join(t for t, _ in skipped[:6])}"
              f"{' …' if len(skipped) > 6 else ''}", file=sys.stderr)
    print(f"  ties: {summed:,} across bundles vs {total_ties:,} in the dataset "
          f"({'partition, none lost' if summed == total_ties else 'MISMATCH'})",
          file=sys.stderr)
    shared_p = sum(r["n_persons_shared"] for r in manifest)
    shared_c = sum(r["n_companies_shared"] for r in manifest)
    print(f"  nodes overlap: {shared_p:,} person-bundle rows and {shared_c:,} "
          f"firm-bundle rows are entities also present in another territory - "
          f"do not sum node counts across bundles", file=sys.stderr)
    print(f"    {'ties':>8} {'firms':>6} {'people':>7} {'%shared':>8}  territory",
          file=sys.stderr)
    for r in manifest[:12]:
        print(f"    {r['n_ties']:8,} {r['n_companies']:6,} {r['n_persons']:7,} "
              f"{r['share_persons_shared']:8}  {r['territory'][:40]}", file=sys.stderr)
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ties", type=int, default=1,
                    help="skip territories with fewer attributed ties than this")
    ap.add_argument("--level", choices=["country", "region", "both"], default="both")
    args = ap.parse_args()

    levels = ["country", "region"] if args.level == "both" else [args.level]
    for level in levels:
        run_level(level, args.min_ties)


if __name__ == "__main__":
    main()
