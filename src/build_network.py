"""Stage 4 - build the network files from the parsed ties.

Produces the standard object for interlocking-directorate research: a
two-mode person x company affiliation network, its one-mode projections, and
two further company-to-company relations that this source supports directly
(corporate directorships, and the compiler's own cross-references between
company dossiers).

Every edge keeps a year and a source citation, so a researcher can slice the
network by period instead of collapsing four decades into one graph.

Entity resolution
    A tie's person_key is a *suggested* grouping (normalised surname plus
    first given initial). This stage adds one further, reversible step: a
    surname-only key is folded into a surname-plus-initial key when exactly
    one such key exists for that surname. Where several exist the key is left
    alone and marked ambiguous, because guessing would be unrecoverable. The
    full crosswalk is written to person_resolution.csv so any user can adopt,
    reject or replace it.

Outputs (data/processed/)
    companies.csv                       company nodes
    persons_resolved.csv                person nodes
    person_resolution.csv               person_key -> resolved key crosswalk
    edges_person_company.csv            two-mode edges, one row per observation-year
    edges_person_company_collapsed.csv  two-mode edges collapsed over time
    edges_company_interlock.csv         companies sharing a director
    edges_person_comembership.csv       people sharing a board
    edges_company_corporate.csv         a company sitting on another's board
    edges_company_reference.csv         cross-references between dossiers
    network_stats.csv                   summary statistics by period
    graphs/*.graphml                    GraphML for Gephi / igraph / NetworkX
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import PLACES, XML_ILLEGAL_RE, ensure_dir, slugify, strip_accents  # noqa: E402
from names import org_key  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC_DIR = os.path.join(ROOT, "data", "processed")
GRAPH_DIR = os.path.join(ROOT, "data", "graphs")

# Roles that constitute board membership proper. Auditors (commissaires aux
# comptes) and salaried managers are recorded but excluded from the interlock
# projection by default, following the convention in the interlock literature
# that an interlock is a shared *board* seat.
BOARD_ROLES = {
    "president",
    "vice_president",
    "president_directeur_general",
    "administrateur_delegue",
    "administrateur",
    "conseil_surveillance",
    "censeur",
}

PERIODS = [
    ("pre_1914", 0, 1913),
    ("1914_1929", 1914, 1929),
    ("1930_1944", 1930, 1944),
    ("1945_1962", 1945, 1962),
    ("post_1962", 1963, 3000),
]


def period_of(year: str) -> str:
    if not year or not year.isdigit():
        return ""
    y = int(year)
    for name, lo, hi in PERIODS:
        if lo <= y <= hi:
            return name
    return ""


def read_csv(name: str) -> list[dict]:
    path = os.path.join(PROC_DIR, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(name: str, rows: list[dict], fields: list[str], subdir: str = "") -> None:
    d = os.path.join(PROC_DIR, subdir) if subdir else PROC_DIR
    ensure_dir(d)
    path = os.path.join(d, name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {os.path.relpath(path, ROOT)}: {len(rows)} rows", file=sys.stderr)


# --- person entity resolution -------------------------------------------
# A single career spans at most about this many years. A wider span after
# folding means two different people were merged, so the fold is refused.
MAX_CAREER_SPAN = 60


def resolve_persons(affiliations: list[dict]) -> tuple[dict[str, str], list[dict]]:
    """Fold surname-only keys into a unique surname+initial key.

    "Katz" is folded into "Katz, M." when Maxime Katz is the only Katz with a
    recorded initial; it is left alone when there is also an "E. Katz", since
    picking one would silently invent an identification. The fold is also
    refused when the two keys' observation years imply a career longer than a
    lifetime, which is the signature of two namesakes rather than one person.
    """
    surname_of: dict[str, str] = {}
    keys = Counter()
    years: dict[str, list[int]] = defaultdict(list)
    for r in affiliations:
        k = r["person_key"]
        if not k:
            continue
        keys[k] += 1
        surname_of.setdefault(k, r.get("surname", ""))
        if r["year"].isdigit():
            years[k].append(int(r["year"]))

    # Group keys by their surname stem. make_person_key appends "-<initial>".
    by_stem: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        stem = re.sub(r"-[a-z0-9]$", "", k)
        by_stem[stem].append(k)

    def span_ok(a: str, b: str) -> bool:
        ys = years.get(a, []) + years.get(b, [])
        return not ys or (max(ys) - min(ys)) <= MAX_CAREER_SPAN

    mapping: dict[str, str] = {}
    crosswalk: list[dict] = []
    for stem, group in by_stem.items():
        bases = [k for k in group if k == stem]
        variants = sorted(k for k in group if k != stem)
        for k in group:
            resolved, rule, ambiguous = k, "identity", 0
            if k in bases and len(variants) == 1:
                if span_ok(k, variants[0]):
                    resolved, rule = variants[0], "folded_unique_initial"
                else:
                    rule, ambiguous = "unfolded_year_span", 1
            elif k in bases and len(variants) > 1:
                rule, ambiguous = "unfolded_ambiguous", 1
            mapping[k] = resolved
            ys = years.get(k, [])
            crosswalk.append(
                {
                    "person_key": k,
                    "person_key_resolved": resolved,
                    "surname": surname_of.get(k, ""),
                    "rule": rule,
                    "ambiguous": ambiguous,
                    "n_observations": keys[k],
                    "n_sibling_variants": len(variants),
                    "first_year": min(ys) if ys else "",
                    "last_year": max(ys) if ys else "",
                }
            )
    crosswalk.sort(key=lambda r: (r["surname"], r["person_key"]))
    return mapping, crosswalk


ANNOT_DATE_RE = re.compile(r"^\s*(?:ca\.?\s*)?1[5-9]\d{2}(?:\s*[-–]\s*(?:1[5-9]\d{2}|20\d{2}))?\s*$")
ANNOT_PARTICLE_START_RE = re.compile(r"^(?:de|d['’]|du|des|le|la|les|[aà]|en|et|=|ex-?|voir)\b", re.I)
ANNOT_ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9&.\-]{2,14}$")
# Short keys collide once legal forms and stopwords are stripped, so a
# name-based match needs this much surviving signal.
MIN_ANNOT_KEY_LEN = 8


def annotation_candidate_ties(
    affiliations: list[dict],
    mapping: dict[str, str],
    acronym_index: dict[str, str],
    known_keys: dict[str, str],
) -> list[dict]:
    """Resolve the compiler's inline affiliation notes into candidate ties.

    Board lists carry the compiler's own identification of a director's other
    positions: "A. R. Fontaine (Distill. Indoch.)", "Paul Philippart [C.I.L.]".
    That is interlock evidence, but as abbreviations rather than names, so only
    a minority resolve to a company node and naive matching produces nonsense
    ("de Paris" onto a firm called "A Paris").

    These are therefore emitted as clearly-labelled *candidates* and are not
    part of the network. Guards: no bare dates or place names, no fragments
    opening with a particle, and either an all-capitals acronym present in the
    catalogue or a multi-word name whose key retains enough signal to be
    distinctive.
    """
    out: dict[tuple, dict] = {}
    for r in affiliations:
        if not r["annotation"] or not r["person_key"]:
            continue
        pid = mapping.get(r["person_key"], r["person_key"])
        for piece in (p.strip(" .,;=") for p in r["annotation"].split(";")):
            if len(piece) < 3 or ANNOT_DATE_RE.match(piece):
                continue
            if ANNOT_PARTICLE_START_RE.match(piece):
                continue
            if strip_accents(piece).lower() in PLACES:
                continue
            target, method = "", ""
            if ANNOT_ACRONYM_RE.match(piece) and piece.upper() in acronym_index:
                target, method = acronym_index[piece.upper()], "acronym"
            else:
                k = org_key(piece)
                if len(piece.split()) >= 2 and len(k) >= MIN_ANNOT_KEY_LEN and k in known_keys:
                    target, method = k, "name"
            key = (pid, piece.lower(), target)
            if key in out:
                out[key]["n_observations"] += 1
                continue
            out[key] = {
                "person_id": pid,
                "annotation_raw": piece,
                "candidate_company_id": target,
                "candidate_company_name": known_keys.get(target, ""),
                "match_method": method or "unmatched",
                "from_company_id": r["company_key"],
                "year": r["year"],
                "source_ref": r["source_ref"],
                "doc_id": r["doc_id"],
                "n_observations": 1,
            }
    rows = sorted(out.values(), key=lambda r: (r["match_method"] == "unmatched",
                                               -r["n_observations"]))
    return rows


def company_duplicate_candidates(companies: dict[str, dict]) -> list[dict]:
    """Flag company keys that plausibly denote the same firm.

    Name-based keying merges abbreviation variants ("Cie" / "Compagnie") but
    cannot merge names that differ in content, e.g. "abattoirs municipaux
    industriels maroc" against "abattoirs municipaux maroc" - one source drops
    a word. Rather than guess, the pairs are listed for the researcher to
    accept or reject. Candidates are keys where one is a prefix of the other,
    or where their token sets stand in a subset relation.
    """
    def tokens(name: str) -> frozenset[str]:
        t = re.split(r"[^a-z0-9]+", slugify(strip_accents(name).lower()))
        return frozenset(x for x in t if len(x) > 2)

    items = [(k, c["name"], tokens(c["name"])) for k, c in companies.items()]
    by_first: dict[str, list[tuple]] = defaultdict(list)
    for k, name, toks in items:
        if toks:
            # Block on the longest token to keep the comparison tractable.
            by_first[max(toks, key=len)].append((k, name, toks))

    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for block in by_first.values():
        if len(block) < 2 or len(block) > 400:
            continue
        for i in range(len(block)):
            for j in range(i + 1, len(block)):
                k1, n1, t1 = block[i]
                k2, n2, t2 = block[j]
                if k1 == k2:
                    continue
                pair = (min(k1, k2), max(k1, k2))
                if pair in seen:
                    continue
                reason = ""
                if k1.startswith(k2) or k2.startswith(k1):
                    reason = "key_prefix"
                elif t1 < t2 or t2 < t1:
                    reason = "token_subset"
                if not reason:
                    continue
                seen.add(pair)
                out.append(
                    {
                        "company_id_1": pair[0],
                        "company_id_2": pair[1],
                        "name_1": n1 if pair[0] == k1 else n2,
                        "name_2": n2 if pair[0] == k1 else n1,
                        "reason": reason,
                    }
                )
    out.sort(key=lambda r: (r["reason"], r["company_id_1"]))
    return out


# --- GraphML -------------------------------------------------------------
def _xml_escape(v: str) -> str:
    """Escape a value for XML, dropping characters XML 1.0 cannot carry.

    Escaping alone is not enough: control characters such as NUL are illegal
    in XML even as entities, and the PDF text layer contains them. Emitting one
    produces a GraphML file that no parser will load, which is a broken
    deliverable rather than a visible error, so they are stripped here as well
    as in common.clean_text.
    """
    s = XML_ILLEGAL_RE.sub(" ", str(v))
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_graphml(
    path: str,
    nodes: list[tuple[str, dict]],
    edges: list[tuple[str, str, dict]],
    directed: bool = False,
) -> None:
    """Write GraphML with the standard library only.

    Avoids a networkx dependency for the pipeline itself; the file loads in
    Gephi, igraph, NetworkX and Cytoscape.
    """
    ensure_dir(os.path.dirname(path))
    node_attrs: dict[str, str] = {}
    for _, d in nodes:
        for k, v in d.items():
            node_attrs.setdefault(k, "long" if isinstance(v, int) else "string")
    edge_attrs: dict[str, str] = {}
    for _, _, d in edges:
        for k, v in d.items():
            edge_attrs.setdefault(k, "long" if isinstance(v, int) else "string")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write(
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns '
            'http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">\n'
        )
        for k, t in node_attrs.items():
            fh.write(f'  <key id="n_{k}" for="node" attr.name="{k}" attr.type="{t}"/>\n')
        for k, t in edge_attrs.items():
            fh.write(f'  <key id="e_{k}" for="edge" attr.name="{k}" attr.type="{t}"/>\n')
        fh.write(f'  <graph id="G" edgedefault="{"directed" if directed else "undirected"}">\n')
        for nid, d in nodes:
            fh.write(f'    <node id="{_xml_escape(nid)}">\n')
            for k, v in d.items():
                fh.write(f'      <data key="n_{k}">{_xml_escape(v)}</data>\n')
            fh.write("    </node>\n")
        for i, (s, t, d) in enumerate(edges):
            fh.write(f'    <edge id="e{i}" source="{_xml_escape(s)}" target="{_xml_escape(t)}">\n')
            for k, v in d.items():
                fh.write(f'      <data key="e_{k}">{_xml_escape(v)}</data>\n')
            fh.write("    </edge>\n")
        fh.write("  </graph>\n</graphml>\n")
    print(f"wrote {os.path.relpath(path, ROOT)}: {len(nodes)} nodes, {len(edges)} edges",
          file=sys.stderr)


# --- main ----------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-interlock-weight", type=int, default=1,
                    help="drop interlock edges below this many shared directors")
    ap.add_argument("--graphml-max-nodes", type=int, default=200000,
                    help="skip GraphML export above this node count")
    ap.add_argument("--no-person-index", action="store_true",
                    help="exclude stage 3b (the annuaire indexes) from the network")
    ap.add_argument("--with-prose", action="store_true",
                    help="include stage 3c (prose-reported boards). Off by "
                         "default: hand-audited precision is ~90%%, below the "
                         "structured parser's, so it is opt-in.")
    args = ap.parse_args()

    documents = read_csv("documents.csv")
    affiliations = [r for r in read_csv("affiliations.csv") if r["company_key"] and r["person_key"]]
    org_aff = [r for r in read_csv("org_affiliations.csv") if r["company_key"] and r["member_key"]]

    # Stage 3b: the person-indexed annuaires. Included by default. A large
    # share of colonial firms were quoted on the Paris Bourse, so the Desfossés
    # index is a colonial source and not a foreign one; excluding it because
    # its firms also include metropolitan companies would drop real colonial
    # boards to avoid admitting some non-colonial ones. Every row keeps
    # `source_genre`, so a study that wants only the dossier evidence can
    # filter it back out, or rebuild with --no-person-index.
    n_index = 0
    if not args.no_person_index:
        idx = read_csv("affiliations_person_index.csv")
        for r in idx:
            r.setdefault("source_genre", "person_index")
        affiliations += [r for r in idx if r["company_key"] and r.get("person_key")]
        org_aff += [r for r in idx if r["company_key"] and r.get("member_key")]
        n_index = sum(1 for r in idx if r["company_key"]
                      and (r.get("person_key") or r.get("member_key")))
        print(f"person-index rows merged: {n_index:,}", file=sys.stderr)
    # Stage 3c: boards reported in running prose. Opt-in, because a hand audit
    # of random samples puts precision near 90% against the structured
    # parser's high nineties. Every row is tagged `prose`, so including it and
    # filtering later is equivalent to excluding it here.
    if args.with_prose:
        pr = read_csv("affiliations_prose.csv")
        for r in pr:
            r.setdefault("source_genre", "prose")
        affiliations += [r for r in pr if r["company_key"] and r.get("person_key")]
        print(f"prose rows merged: {len(pr):,}", file=sys.stderr)

    for r in affiliations + org_aff:
        r.setdefault("source_genre", "dossier")
    attributes = read_csv("company_attributes.csv")
    refs = read_csv("doc_references.csv")

    if not affiliations:
        raise SystemExit("no attributed affiliations found - run src/parse_ties.py first")

    # ---- person resolution ---------------------------------------------
    mapping, crosswalk = resolve_persons(affiliations)
    write_csv("person_resolution.csv", crosswalk,
              ["person_key", "person_key_resolved", "surname", "rule", "ambiguous",
               "n_observations", "n_sibling_variants", "first_year", "last_year"])

    for r in affiliations:
        r["person_id"] = mapping.get(r["person_key"], r["person_key"])
        r["period"] = period_of(r["year"])
        r["is_board_seat"] = 1 if r["role"] in BOARD_ROLES else 0

    # ---- company nodes -------------------------------------------------
    # Seeded from the catalogue, then extended with firms seen only inside
    # directory entries (many small local companies appear nowhere else).
    companies: dict[str, dict] = {}
    for d in documents:
        if d["entry_type"] != "company":
            continue
        key = org_key(d["name_normalised"] or d["name_listed"])
        if not key:
            continue
        c = companies.setdefault(
            key,
            {
                "company_id": key,
                "name": d["name_normalised"] or d["name_listed"],
                "acronym": d["acronym"],
                "in_catalogue": 1,
                "doc_ids": set(),
                "regions": set(),
                "countries": set(),
                "sectors": set(),
                "groups": set(),
                "place_listed": d["place_listed"],
                "legal_form": d["legal_form_listed"],
                "year_start": d["year_start"],
                "year_end": d["year_end"],
            },
        )
        c["doc_ids"].add(d["doc_id"])
        for r in (d["all_regions"] or d["region"]).split("; "):
            if r:
                c["regions"].add(r)
        if d["country"]:
            c["countries"].add(d["country"])
        for s in (d["all_sectors"] or d["sector"]).split("; "):
            if s:
                c["sectors"].add(s)
        if d["group_path"]:
            c["groups"].add(d["group_path"])
        c["acronym"] = c["acronym"] or d["acronym"]
        c["place_listed"] = c["place_listed"] or d["place_listed"]
        c["legal_form"] = c["legal_form"] or d["legal_form_listed"]
        c["year_start"] = c["year_start"] or d["year_start"]
        c["year_end"] = c["year_end"] or d["year_end"]

    def ensure_company(key: str, name: str, row: dict) -> dict:
        c = companies.get(key)
        if c is None:
            c = companies[key] = {
                "company_id": key,
                "name": name,
                "acronym": "",
                "in_catalogue": 0,
                "doc_ids": set(),
                "regions": set(),
                "countries": set(),
                "sectors": set(),
                "groups": set(),
                "place_listed": "",
                "legal_form": "",
                "year_start": "",
                "year_end": "",
            }
        if row.get("region"):
            c["regions"].add(row["region"])
        if row.get("country"):
            c["countries"].add(row["country"])
        if row.get("sector"):
            c["sectors"].add(row["sector"])
        if row.get("doc_id"):
            c["doc_ids"].add(row["doc_id"])
        return c

    for r in affiliations:
        ensure_company(r["company_key"], r["company_name"], r)
    for r in org_aff:
        ensure_company(r["company_key"], r["company_name"], r)
        ensure_company(r["member_key"], r["name_clean"], r)

    # Attribute observations, latest year wins.
    attr_by_company: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
    for a in attributes:
        k = a["company_key"]
        if not k:
            continue
        prev = attr_by_company[k].get(a["attribute"])
        if prev is None or (a["year"] or "") >= (prev[1] or ""):
            attr_by_company[k][a["attribute"]] = (a["value"], a["year"])

    ties_per_company = Counter(r["company_key"] for r in affiliations)
    board_ties_per_company = Counter(
        r["company_key"] for r in affiliations if r["is_board_seat"]
    )
    directors_per_company: dict[str, set[str]] = defaultdict(set)
    years_per_company: dict[str, list[int]] = defaultdict(list)
    for r in affiliations:
        if r["is_board_seat"]:
            directors_per_company[r["company_key"]].add(r["person_id"])
        if r["year"].isdigit():
            years_per_company[r["company_key"]].append(int(r["year"]))

    company_rows = []
    for key, c in companies.items():
        attrs = attr_by_company.get(key, {})
        ys = years_per_company.get(key, [])
        company_rows.append(
            {
                "company_id": key,
                "name": c["name"],
                "acronym": c["acronym"],
                "in_catalogue": c["in_catalogue"],
                "n_documents": len(c["doc_ids"]),
                "regions": "; ".join(sorted(c["regions"])),
                "countries": "; ".join(sorted(c["countries"])),
                "sectors": "; ".join(sorted(c["sectors"])),
                "corporate_group": "; ".join(sorted(c["groups"])),
                "place_listed": c["place_listed"],
                "legal_form_listed": c["legal_form"],
                "year_start_listed": c["year_start"],
                "year_end_listed": c["year_end"],
                "founded_date_observed": attrs.get("founded_date", ("", ""))[0],
                "capital_observed": attrs.get("capital", ("", ""))[0],
                "capital_year": attrs.get("capital", ("", ""))[1],
                "head_office_observed": attrs.get("head_office", ("", ""))[0],
                "n_ties": ties_per_company.get(key, 0),
                "n_board_ties": board_ties_per_company.get(key, 0),
                "n_directors": len(directors_per_company.get(key, ())),
                "first_year_observed": min(ys) if ys else "",
                "last_year_observed": max(ys) if ys else "",
            }
        )
    company_rows.sort(key=lambda r: (-r["n_board_ties"], r["name"]))
    write_csv("companies.csv", company_rows,
              ["company_id", "name", "acronym", "in_catalogue", "n_documents", "regions",
               "countries", "sectors", "corporate_group", "place_listed",
               "legal_form_listed", "year_start_listed", "year_end_listed",
               "founded_date_observed", "capital_observed", "capital_year",
               "head_office_observed", "n_ties", "n_board_ties", "n_directors",
               "first_year_observed", "last_year_observed"])

    # The compiler's inline affiliation notes, resolved where possible. Not
    # part of the network - see the docstring on annotation_candidate_ties.
    acronym_owners: dict[str, set[str]] = defaultdict(set)
    for d in documents:
        if d["entry_type"] != "company":
            continue
        k = org_key(d["name_normalised"] or d["name_listed"])
        if not k:
            continue
        for a in [d["acronym"], *d["alias"].split("; ")]:
            a = a.strip()
            if len(a) >= 3:
                acronym_owners[a.upper()].add(k)
    # An acronym claimed by more than one firm identifies nothing: "BAO" is
    # both the Banque de l'Afrique occidentale and a brewery alias, and
    # first-wins matching silently picked the wrong one.
    acronym_index = {a: next(iter(ks)) for a, ks in acronym_owners.items() if len(ks) == 1}
    ambiguous_acronyms = sum(1 for ks in acronym_owners.values() if len(ks) > 1)
    print(f"acronym index: {len(acronym_index)} unique, "
          f"{ambiguous_acronyms} ambiguous and unused", file=sys.stderr)
    known_keys = {k: c["name"] for k, c in companies.items()}
    cand = annotation_candidate_ties(affiliations, mapping, acronym_index, known_keys)
    write_csv("candidate_ties_from_annotations.csv", cand,
              ["person_id", "annotation_raw", "candidate_company_id",
               "candidate_company_name", "match_method", "from_company_id",
               "year", "source_ref", "doc_id", "n_observations"])

    dupes = company_duplicate_candidates(companies)
    write_csv("company_duplicate_candidates.csv", dupes,
              ["company_id_1", "company_id_2", "name_1", "name_2", "reason"])

    # ---- person nodes --------------------------------------------------
    people: dict[str, dict] = {}
    for r in affiliations:
        pid = r["person_id"]
        p = people.setdefault(
            pid,
            {
                "person_id": pid,
                "surname": r["surname"],
                "given_variants": set(),
                "name_variants": set(),
                "raw_keys": set(),
                "companies": set(),
                "board_companies": set(),
                "roles": Counter(),
                "years": [],
                "regions": set(),
                "sectors": set(),
                "annotations": set(),
            },
        )
        if r["given"]:
            p["given_variants"].add(r["given"])
        p["name_variants"].add(r["name_clean"])
        p["raw_keys"].add(r["person_key"])
        p["companies"].add(r["company_key"])
        if r["is_board_seat"]:
            p["board_companies"].add(r["company_key"])
        p["roles"][r["role"]] += 1
        if r["year"].isdigit():
            p["years"].append(int(r["year"]))
        if r["region"]:
            p["regions"].add(r["region"])
        if r["sector"]:
            p["sectors"].add(r["sector"])
        if r["annotation"]:
            p["annotations"].add(r["annotation"])

    person_rows = []
    for pid, p in people.items():
        person_rows.append(
            {
                "person_id": pid,
                "surname": p["surname"],
                "given_variants": "; ".join(sorted(p["given_variants"])),
                "name_variants": "; ".join(sorted(p["name_variants"])),
                "n_name_variants": len(p["name_variants"]),
                "merged_keys": "; ".join(sorted(p["raw_keys"])),
                "n_companies": len(p["companies"]),
                "n_board_companies": len(p["board_companies"]),
                "n_observations": sum(p["roles"].values()),
                "top_role": p["roles"].most_common(1)[0][0] if p["roles"] else "",
                "roles": "; ".join(f"{k}:{v}" for k, v in p["roles"].most_common()),
                "first_year": min(p["years"]) if p["years"] else "",
                "last_year": max(p["years"]) if p["years"] else "",
                "regions": "; ".join(sorted(p["regions"])),
                "sectors": "; ".join(sorted(p["sectors"])),
                "affiliation_notes": "; ".join(sorted(p["annotations"]))[:500],
            }
        )
    person_rows.sort(key=lambda r: (-r["n_board_companies"], -r["n_observations"]))
    write_csv("persons_resolved.csv", person_rows,
              ["person_id", "surname", "given_variants", "n_companies",
               "n_board_companies", "n_observations", "top_role", "roles",
               "first_year", "last_year", "regions", "sectors", "n_name_variants",
               "name_variants", "merged_keys", "affiliation_notes"])

    # ---- two-mode edges ------------------------------------------------
    two_mode: dict[tuple, dict] = {}
    for r in affiliations:
        k = (r["person_id"], r["company_key"], r["role"], r["year"])
        e = two_mode.get(k)
        if e is None:
            two_mode[k] = {
                "person_id": r["person_id"],
                "company_id": r["company_key"],
                "role": r["role"],
                "year": r["year"],
                "period": r["period"],
                "is_board_seat": r["is_board_seat"],
                "n_observations": 1,
                "source_refs": {r["source_ref"]} if r["source_ref"] else set(),
                "doc_ids": {r["doc_id"]},
                "genres": {r.get("source_genre", "dossier")},
            }
        else:
            e["n_observations"] += 1
            if r["source_ref"]:
                e["source_refs"].add(r["source_ref"])
            e["doc_ids"].add(r["doc_id"])
            e["genres"].add(r.get("source_genre", "dossier"))

    tm_rows = []
    for e in two_mode.values():
        tm_rows.append(
            {
                **{k: v for k, v in e.items()
                   if k not in {"source_refs", "doc_ids", "genres"}},
                "source_refs": " | ".join(sorted(e["source_refs"]))[:400],
                "doc_ids": "; ".join(sorted(e["doc_ids"]))[:300],
                # Which extraction genre supports this edge, so a study can
                # restrict to the dossier evidence without rebuilding.
                "source_genre": "; ".join(sorted(e["genres"])),
            }
        )
    tm_rows.sort(key=lambda r: (r["company_id"], r["year"], r["person_id"]))
    write_csv("edges_person_company.csv", tm_rows,
              ["person_id", "company_id", "role", "year", "period", "is_board_seat",
               "n_observations", "source_refs", "doc_ids", "source_genre"])

    collapsed: dict[tuple, dict] = {}
    for r in affiliations:
        k = (r["person_id"], r["company_key"])
        e = collapsed.setdefault(
            k,
            {
                "person_id": r["person_id"],
                "company_id": r["company_key"],
                "n_observations": 0,
                "years": [],
                "roles": Counter(),
                "board_seat": 0,
            },
        )
        e["n_observations"] += 1
        if r["year"].isdigit():
            e["years"].append(int(r["year"]))
        e["roles"][r["role"]] += 1
        e["board_seat"] = max(e["board_seat"], r["is_board_seat"])
    coll_rows = [
        {
            "person_id": e["person_id"],
            "company_id": e["company_id"],
            "n_observations": e["n_observations"],
            "first_year": min(e["years"]) if e["years"] else "",
            "last_year": max(e["years"]) if e["years"] else "",
            "top_role": e["roles"].most_common(1)[0][0],
            "roles": "; ".join(f"{k}:{v}" for k, v in e["roles"].most_common()),
            "is_board_seat": e["board_seat"],
        }
        for e in collapsed.values()
    ]
    coll_rows.sort(key=lambda r: (r["company_id"], r["person_id"]))
    write_csv("edges_person_company_collapsed.csv", coll_rows,
              ["person_id", "company_id", "n_observations", "first_year", "last_year",
               "top_role", "roles", "is_board_seat"])

    # ---- one-mode projections ------------------------------------------
    # Interlocks are built from board seats only, and per period as well as
    # overall: two firms sharing a director thirty years apart are not
    # interlocked in any meaningful sense.
    seats_by_company: dict[str, set[str]] = defaultdict(set)
    seats_by_person: dict[str, set[str]] = defaultdict(set)
    seats_by_company_period: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in affiliations:
        if not r["is_board_seat"]:
            continue
        seats_by_company[r["company_key"]].add(r["person_id"])
        seats_by_person[r["person_id"]].add(r["company_key"])
        if r["period"]:
            seats_by_company_period[(r["company_key"], r["period"])].add(r["person_id"])

    interlock: dict[tuple[str, str], set[str]] = defaultdict(set)
    for person, comps in seats_by_person.items():
        cs = sorted(comps)
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                interlock[(cs[i], cs[j])].add(person)

    period_interlock: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    persons_period: dict[tuple[str, str], set[str]] = defaultdict(set)
    for (comp, per), persons in seats_by_company_period.items():
        for p in persons:
            persons_period[(p, per)].add(comp)
    for (p, per), comps in persons_period.items():
        cs = sorted(comps)
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                period_interlock[(cs[i], cs[j], per)].add(p)

    name_of = {k: c["name"] for k, c in companies.items()}
    il_rows = []
    for (a, b), persons in interlock.items():
        if len(persons) < args.min_interlock_weight:
            continue
        il_rows.append(
            {
                "company_id_1": a,
                "company_id_2": b,
                "company_name_1": name_of.get(a, ""),
                "company_name_2": name_of.get(b, ""),
                "weight": len(persons),
                "shared_directors": "; ".join(sorted(persons))[:400],
            }
        )
    il_rows.sort(key=lambda r: -r["weight"])
    write_csv("edges_company_interlock.csv", il_rows,
              ["company_id_1", "company_id_2", "company_name_1", "company_name_2",
               "weight", "shared_directors"])

    pil_rows = [
        {
            "company_id_1": a,
            "company_id_2": b,
            "period": per,
            "weight": len(persons),
            "shared_directors": "; ".join(sorted(persons))[:300],
        }
        for (a, b, per), persons in period_interlock.items()
        if len(persons) >= args.min_interlock_weight
    ]
    pil_rows.sort(key=lambda r: (r["period"], -r["weight"]))
    write_csv("edges_company_interlock_by_period.csv", pil_rows,
              ["company_id_1", "company_id_2", "period", "weight", "shared_directors"])

    comem: dict[tuple[str, str], set[str]] = defaultdict(set)
    for company, persons in seats_by_company.items():
        ps = sorted(persons)
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                comem[(ps[i], ps[j])].add(company)
    cm_rows = [
        {
            "person_id_1": a,
            "person_id_2": b,
            "weight": len(cs),
            "shared_companies": "; ".join(sorted(cs))[:400],
        }
        for (a, b), cs in comem.items()
    ]
    cm_rows.sort(key=lambda r: -r["weight"])
    write_csv("edges_person_comembership.csv", cm_rows,
              ["person_id_1", "person_id_2", "weight", "shared_companies"])

    # ---- corporate directorships (directed) ----------------------------
    corp: dict[tuple[str, str], dict] = {}
    for r in org_aff:
        k = (r["member_key"], r["company_key"])
        if k[0] == k[1]:
            continue
        e = corp.setdefault(
            k,
            {
                "from_company_id": r["member_key"],
                "to_company_id": r["company_key"],
                "from_name": r["name_clean"],
                "to_name": r["company_name"],
                "n_observations": 0,
                "years": [],
                "roles": Counter(),
            },
        )
        e["n_observations"] += 1
        if r["year"].isdigit():
            e["years"].append(int(r["year"]))
        e["roles"][r["role"]] += 1
    corp_rows = [
        {
            "from_company_id": e["from_company_id"],
            "to_company_id": e["to_company_id"],
            "from_name": e["from_name"],
            "to_name": e["to_name"],
            "n_observations": e["n_observations"],
            "first_year": min(e["years"]) if e["years"] else "",
            "last_year": max(e["years"]) if e["years"] else "",
            "roles": "; ".join(f"{k}:{v}" for k, v in e["roles"].most_common()),
        }
        for e in corp.values()
    ]
    corp_rows.sort(key=lambda r: -r["n_observations"])
    write_csv("edges_company_corporate.csv", corp_rows,
              ["from_company_id", "to_company_id", "from_name", "to_name",
               "n_observations", "first_year", "last_year", "roles"])

    # ---- dossier cross-references (directed) ---------------------------
    doc_company: dict[str, tuple[str, str]] = {}
    for d in documents:
        if d["entry_type"] != "company":
            continue
        k = org_key(d["name_normalised"] or d["name_listed"])
        if k:
            doc_company[d["doc_id"]] = (k, d["name_normalised"] or d["name_listed"])
    ref_rows: dict[tuple[str, str], dict] = {}
    for r in refs:
        src = doc_company.get(r["from_doc_id"])
        dst = doc_company.get(r["to_doc_id"])
        if not src or not dst or src[0] == dst[0]:
            continue
        k = (src[0], dst[0])
        e = ref_rows.get(k)
        if e is None:
            ref_rows[k] = {
                "from_company_id": src[0],
                "to_company_id": dst[0],
                "from_name": src[1],
                "to_name": dst[1],
                "n_references": 1,
            }
        else:
            e["n_references"] += 1
    rr = sorted(ref_rows.values(), key=lambda r: -r["n_references"])
    write_csv("edges_company_reference.csv", rr,
              ["from_company_id", "to_company_id", "from_name", "to_name", "n_references"])

    # ---- GraphML -------------------------------------------------------
    ensure_dir(GRAPH_DIR)
    comp_by_id = {r["company_id"]: r for r in company_rows}
    pers_by_id = {r["person_id"]: r for r in person_rows}

    # Two-mode network.
    used_c = {e["company_id"] for e in coll_rows}
    used_p = {e["person_id"] for e in coll_rows}
    if len(used_c) + len(used_p) <= args.graphml_max_nodes:
        nodes = [
            (f"C:{cid}", {
                "mode": "company",
                "label": comp_by_id.get(cid, {}).get("name", cid),
                "sectors": comp_by_id.get(cid, {}).get("sectors", ""),
                "regions": comp_by_id.get(cid, {}).get("regions", ""),
                "n_directors": comp_by_id.get(cid, {}).get("n_directors", 0),
            })
            for cid in sorted(used_c)
        ] + [
            (f"P:{pid}", {
                "mode": "person",
                "label": (pers_by_id.get(pid, {}).get("name_variants", pid) or pid).split("; ")[0],
                "n_board_companies": pers_by_id.get(pid, {}).get("n_board_companies", 0),
            })
            for pid in sorted(used_p)
        ]
        edges = [
            (f"P:{e['person_id']}", f"C:{e['company_id']}", {
                "top_role": e["top_role"],
                "first_year": str(e["first_year"]),
                "last_year": str(e["last_year"]),
                "n_observations": e["n_observations"],
                "is_board_seat": e["is_board_seat"],
            })
            for e in coll_rows
        ]
        write_graphml(os.path.join(GRAPH_DIR, "two_mode_person_company.graphml"), nodes, edges)
    else:
        print(f"skipped two-mode GraphML: {len(used_c) + len(used_p)} nodes "
              f"exceeds --graphml-max-nodes", file=sys.stderr)

    # Company interlock network.
    il_nodes_ids = sorted({e["company_id_1"] for e in il_rows} | {e["company_id_2"] for e in il_rows})
    if len(il_nodes_ids) <= args.graphml_max_nodes:
        nodes = [
            (cid, {
                "label": comp_by_id.get(cid, {}).get("name", cid),
                "sectors": comp_by_id.get(cid, {}).get("sectors", ""),
                "regions": comp_by_id.get(cid, {}).get("regions", ""),
                "countries": comp_by_id.get(cid, {}).get("countries", ""),
                "n_directors": comp_by_id.get(cid, {}).get("n_directors", 0),
                "first_year": str(comp_by_id.get(cid, {}).get("first_year_observed", "")),
                "last_year": str(comp_by_id.get(cid, {}).get("last_year_observed", "")),
            })
            for cid in il_nodes_ids
        ]
        edges = [
            (e["company_id_1"], e["company_id_2"], {"weight": e["weight"]}) for e in il_rows
        ]
        write_graphml(os.path.join(GRAPH_DIR, "company_interlock.graphml"), nodes, edges)
    else:
        print(f"skipped interlock GraphML: {len(il_nodes_ids)} nodes exceeds "
              f"--graphml-max-nodes", file=sys.stderr)

    # ---- summary -------------------------------------------------------
    stats: list[dict] = []
    board = [r for r in affiliations if r["is_board_seat"]]
    stats.append({
        "scope": "all",
        "n_person_company_ties": len(affiliations),
        "n_board_ties": len(board),
        "n_persons": len(person_rows),
        "n_companies": len(company_rows),
        "n_companies_with_board": len(seats_by_company),
        "n_interlock_edges": len(il_rows),
        "n_comembership_edges": len(cm_rows),
        "n_corporate_edges": len(corp_rows),
        "n_reference_edges": len(rr),
    })
    for name, _, _ in PERIODS:
        sub = [r for r in board if r["period"] == name]
        comps = {r["company_key"] for r in sub}
        pers = {r["person_id"] for r in sub}
        edges_p = [e for e in pil_rows if e["period"] == name]
        stats.append({
            "scope": name,
            "n_person_company_ties": len([r for r in affiliations if r["period"] == name]),
            "n_board_ties": len(sub),
            "n_persons": len(pers),
            "n_companies": len(comps),
            "n_companies_with_board": len(comps),
            "n_interlock_edges": len(edges_p),
            "n_comembership_edges": "",
            "n_corporate_edges": "",
            "n_reference_edges": "",
        })
    sub = [r for r in board if not r["period"]]
    stats.append({
        "scope": "undated",
        "n_person_company_ties": len([r for r in affiliations if not r["period"]]),
        "n_board_ties": len(sub),
        "n_persons": len({r["person_id"] for r in sub}),
        "n_companies": len({r["company_key"] for r in sub}),
        "n_companies_with_board": "",
        "n_interlock_edges": "",
        "n_comembership_edges": "",
        "n_corporate_edges": "",
        "n_reference_edges": "",
    })
    write_csv("network_stats.csv", stats,
              ["scope", "n_person_company_ties", "n_board_ties", "n_persons",
               "n_companies", "n_companies_with_board", "n_interlock_edges",
               "n_comembership_edges", "n_corporate_edges", "n_reference_edges"])

    print("\n--- summary ---", file=sys.stderr)
    for s in stats:
        print(f"  {s['scope']:12s} ties={s['n_person_company_ties']:>7} "
              f"board={s['n_board_ties']:>7} persons={s['n_persons']:>6} "
              f"companies={s['n_companies']:>6} interlocks={s['n_interlock_edges']:>7}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
