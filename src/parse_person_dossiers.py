"""Stage 3j - the compiler's dossiers on individuals, read from the person's side.

    python3 src/parse_person_dossiers.py            # after stage 4
    python3 src/parse_person_dossiers.py --audit 15 # a random sample to hand-check

    data/processed/affiliations_person_dossiers.csv

Every reader in this tree is **company-anchored**: find a board heading, read
the members under it. The catalogue also holds 240 entries whose subject is a
*person* — `Noël (Octave)(1846-1918)`, `Gorgeu (Maurice)(1862-1935), banquier`
— and those are written the other way round. The man is named once, in the
entry's own title, and the body lists what he sat on:

    Administrateur de la Banque auxiliaire, Union parisienne et provinciale
    Administrateur du comité de Paris de la Banque de Tunisie (mai 1886).
    Administrateur délégué des Charbonnages du Tonkin (1895-1898).

Nothing was reading that shape. **Company dossiers yield a tie 67.2% of the
time; person dossiers, 21.3%** — and the gap is not that the documents are
empty, it is that they are inside out.

## The subject is free, which is why this genre is cheap and safe

`parse_mandates` and `parse_offices` spend most of their code deciding *whose*
title a phrase is, because a governor-general is named as an institution far
more often than as a man. Here the catalogue already answers it: the subject is
the entry's `name_listed`, parsed by the same `names.parse_person_name` every
other stage uses. A role line in the body needs no subject resolution at all.

Two entries the subject rule has to refuse:

- **Firms filed as people.** `Jacques Menasché & Cie (1926-1933), Paris` is an
  entry of type `person` and is a company. `names.looks_like_org` rejects it.
- **Titles with no personal name**, which would key to a surname bucket.

## The company side is stage 3d's resolver, not a new one

A role line names its company in the compiler's own abbreviated register, so
`resolve_annotations.resolve` does the matching: prefix-in-order against
`companies.csv`, ambiguity dropped rather than guessed, place names refused.
**A line whose company does not resolve is not emitted.** That is a deliberate
recall sacrifice: an unresolved company name would be a node the graph cannot
join to anything, so it would inflate the tie count without connecting a
single pair of firms.

## Offices are not directorships, and this genre is full of them

The same line register carries the man's public career:

    Administrateur de 5e classe des colonies (8 février 1898).
    Vice-président de l'Office colonial par décret du ministre des colonies.
    Membre du conseil de protectorat,
    président de la chambre de commerce de Tahiti

`OFFICE_TAIL_RE` refuses these before resolution is attempted. Requiring the
company to resolve would catch most of them anyway — *the colonies* is not a
firm — but refusing them explicitly keeps the reason in the output, and the
office-holding they describe is `parse_offices`'s job, already done.

Dates in parentheses after the company (`(1895-1898)`, `(mai 1886)`) are kept
when present. Few genres in this corpus date a seat at all, and this one dates
roughly a third.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import random
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import resolve_annotations as RA  # noqa: E402
from common import PLACES, plausible_year  # noqa: E402
from names import looks_like_org, parse_person_name  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
TEXT = os.path.join(ROOT, "data", "text")
OUT = os.path.join(PROC, "affiliations_person_dossiers.csv")

# The roles this corpus treats as a board seat, in the order they are written
# at the head of a line. `build_network.BOARD_ROLES` decides which of these
# count as a seat; this stage only records which was claimed.
ROLE_WORDS = [
    ("administrateur_delegue", r"Administrateur[ -]délégué"),
    ("president_dg", r"Président[ -]directeur général"),
    ("vice_president", r"Vice-président"),
    ("president", r"Président(?:e)?"),
    ("administrateur", r"Administrateur"),
    ("directeur_general", r"Directeur général"),
    ("directeur", r"Directeur"),
    ("gerant", r"Gérant"),
    ("censeur", r"Censeur"),
    ("commissaire", r"Commissaire aux comptes"),
    ("membre_conseil", r"Membre du conseil d'administration"),
]
_ROLE_ALT = "|".join(p for _k, p in ROLE_WORDS)

# A role at the head of a line, then `de/du/des/d'`, then the company. Anchored
# at the line start: mid-sentence prose ("il devient administrateur de …") is
# §4d's register and reading it here would double-count.
ROLE_LINE_RE = re.compile(
    rf"(?m)^\s*(?P<former>Ancien\s+|Ex-)?"
    rf"(?P<role>{_ROLE_ALT})\b"
    rf"(?P<mid>[^\n]{{0,14}}?)"
    rf"\s+(?:de|du|des|d[’'])\s+"
    rf"(?P<tail>[^\n]{{3,120}})",
    re.IGNORECASE)

# Public office, not a company board. Checked against the tail before the
# resolver sees it, so the reason survives into the output.
OFFICE_TAIL_RE = re.compile(
    r"^(?:la\s+|le\s+|l[’']\s*)?"
    r"(?:\d+e?\s+classe\b|colonies\b|Office\s+colonial|chambre\s+de\s+commerce"
    r"|chambre\s+d[’']agriculture|conseil\s+(?:de\s+)?(?:protectorat|général"
    r"|municipal|d[’']État|supérieur|privé)|comité\s+d[’']agriculture"
    r"|Affaires\s+(?:indigènes|économiques|politiques)|Résidence\s+supérieure"
    r"|gouvernement|ministère|République|préfecture|municipalité"
    r"|Légion\s+d[’']honneur|syndicat|fédération|union\s+coloniale"
    r"|section\s+|commission\s+|sous-commission)",
    re.IGNORECASE)

# The company name ends at the first of these; what follows is date or comment.
TAIL_CUT_RE = re.compile(r"\s*(?:\(|,\s*(?:puis|devenue?|ancienne?ment)\b|;|\.\s|\.$)")
DATE_RE = re.compile(r"\((?P<body>[^)]{3,40})\)")
YEAR_RE = re.compile(r"\b(1[89]\d{2})\b")

MIN_COMPANY_CHARS = 6

# `SURNAME (Forename)` — the catalogue's own shape for a person entry.
CATALOGUE_NAME_RE = re.compile(r"^(?P<surname>[^()]{2,60}?)\s*\((?P<given>[^)]{1,40})\)")
# A parenthetical holding nothing but a date, with the compiler's hedges.
DATE_ONLY_PAREN_RE = re.compile(
    r"\(\s*(?:ca\.?|v\.|vers|\?)?\s*1[5-9]\d{2}"
    r"(?:\s*[-–]\s*(?:ca\.?|v\.|vers|\?)?\s*1[5-9]\d{2})?\s*\??\s*\)")
# A legal form where a forename should be.
LEGAL_FORM_RE = re.compile(
    r"(?:\bS\.?\s?A\.?(?:R\.?L\.?)?\b|\bSté\b|\bSociété\b|\bCie\b|\bC°\b"
    r"|\bLtd\b|\banon(?:yme)?\b|\bfrères\b|&\s*C)", re.IGNORECASE)

# Institutions filed under `entry_type = person`. `looks_like_org` is tuned to
# company names and lets these through, and each one would otherwise sit in the
# graph as a director.
INSTITUTION_HEAD_RE = re.compile(
    r"^(?:Bureau|Office|Comité|Commission|Syndicat|Fédération|Union|Agence|"
    r"Groupe|Association|Chambre|Institut|Mission|Direction|Service|Caisse|"
    r"Conseil)\b", re.IGNORECASE)
KIN_LOOKBACK = 200      # characters; the window a relative's name can reach

# A dossier is biography, so it names the subject's family and the family's
# seats in the same paragraph. `directeur général des Plantations Hallet` sat
# 105 characters after `fils de Paul-Adolphe Chalamel` and was credited to the
# wrong man. Same rejection the roster parser makes, scoped by distance rather
# than by clause because these lines wrap mid-sentence.
KINSHIP_RE = re.compile(
    r"\b(?:fils|fille|frère|sœur|soeur|père|mère|époux|épouse|veuve|veuf|mari"
    r"|gendre|bru|neveu|nièce|oncle|tante|cousin[e]?|petit-fils|petite-fille"
    r"|beau-(?:père|frère|fils)|belle-(?:mère|sœur|soeur|fille)"
    r"|marié[e]?|remarié[e]?|union avec)\b", re.IGNORECASE)

# What follows the company on the same line. A date or a short gloss is fine;
# a new sentence with prose in it means the line was flowing biography and the
# role may belong to whoever that sentence is about.
NEW_SENTENCE_RE = re.compile(r"[.!?]\s+[A-ZÉÈÀÂ][^\n]{12,}")


def load(name: str) -> list[dict]:
    with open(os.path.join(PROC, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_text(doc_id: str) -> str:
    path = os.path.join(TEXT, f"{doc_id}.txt.gz")
    if not os.path.exists(path):
        return ""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def subject_of(entry: dict) -> dict | None:
    """The person the dossier is about, from the catalogue's own title.

    The catalogue writes `SURNAME (Forename)(dates), gloss`, and the shared
    name parser reads the *first* token as the forename — it returned
    `given=Noël, surname=(Octave)` for `Noël (Octave)`, keying the man under
    `octave-n`. Every row of the first version of this file carried an
    inverted person key, and `checks.py` caught it. The title is therefore
    reordered into `Forename Surname` before the parser sees it, exactly as
    §4g reorders `ASSIS (Henri)`.
    """
    raw = (entry.get("name_listed") or "").strip()
    if not raw:
        return None
    # Cut at the first comma following a closing parenthesis: after it is the
    # compiler's gloss ("banquier à Angers", "puis Louis Ogliastro").
    head = re.split(r"\)\s*,\s*", raw)[0]
    if head != raw and not head.endswith(")"):
        head += ")"
    if INSTITUTION_HEAD_RE.match(head):
        return None
    # Drop parentheticals that are only a date, so the forename slot is the
    # forename: `(1846-1918)`, `(ca 1851-ca 1933)`, `(1875)`.
    head = DATE_ONLY_PAREN_RE.sub("", head).strip()
    head = re.sub(r"\s{2,}", " ", head).strip(" ,;")

    m = CATALOGUE_NAME_RE.match(head)
    if m:
        surname, given = m.group("surname").strip(), m.group("given").strip()
        # `Chaux hydrauliques et ciments d'Algérie (S.A. des)` is a company
        # whose legal form sits where the forename should be.
        if LEGAL_FORM_RE.search(given) or LEGAL_FORM_RE.search(surname):
            return None
        if not surname[:1].isupper():
            return None
        toks = [t for t in re.split(r"[\s\-]+", given) if t]
        if not toks or len(toks) > 3 or not all(t[:1].isupper() for t in toks):
            return None
        head = f"{given} {surname}"
    elif LEGAL_FORM_RE.search(head):
        return None

    # `looks_like_org` is applied to the *reordered* name, not the catalogue
    # form. Tested on `Le Gac de Lansalut (Charles)` it fires on the leading
    # article and refuses a man; tested on `Charles Le Gac de Lansalut` it
    # does not, while still refusing `Georges Taupin & Cie`.
    if looks_like_org(head):
        return None

    parsed = parse_person_name(head)
    if not parsed.get("person_key") or not parsed.get("surname"):
        return None
    # A dossier keyed on a surname alone is a bucket, not a man - the same
    # `key_ambiguous` problem the rest of the dataset flags.
    if not (parsed.get("given") or parsed.get("initials")):
        return None
    return parsed


def role_of(match: re.Match) -> str:
    word = match.group("role").lower()
    mid = (match.group("mid") or "").lower()
    for key, pat in ROLE_WORDS:
        if re.fullmatch(pat, match.group("role"), re.IGNORECASE):
            if key == "administrateur" and "délégué" in mid:
                return "administrateur_delegue"
            return key
    return word


def split_tail(tail: str) -> tuple[str, str]:
    """`(company, year)` from the text after `de`. Empty company if unusable."""
    date = ""
    m = DATE_RE.search(tail)
    if m:
        ys = YEAR_RE.findall(m.group("body"))
        if ys and plausible_year(ys[0]):
            date = ys[0]
    cut = TAIL_CUT_RE.search(tail)
    name = (tail[:cut.start()] if cut else tail).strip(" ,;.·—–-")
    name = re.sub(r"\s{2,}", " ", name)
    return name, date


def extract(entry: dict, text: str, subject: dict, index, by_first) -> tuple[list[dict], Counter]:
    rows, why = [], Counter()
    seen: set[tuple[str, str]] = set()
    for m in ROLE_LINE_RE.finditer(text):
        tail = m.group("tail")
        if OFFICE_TAIL_RE.match(tail.strip()):
            why["office_not_company"] += 1
            continue
        if KINSHIP_RE.search(text[max(0, m.start() - KIN_LOOKBACK):m.start()]):
            why["kin_in_lookback"] += 1
            continue
        name, year = split_tail(tail)
        after = tail[len(name):]
        if NEW_SENTENCE_RE.search(after):
            why["line_runs_into_prose"] += 1
            continue
        if len(name) < MIN_COMPANY_CHARS:
            why["too_short"] += 1
            continue
        cid, cname, method = RA.resolve(name, index, by_first)
        if not cid:
            why[f"unresolved_{method}"] += 1
            continue
        role = role_of(m)
        if (subject["person_key"], cid) in seen:
            why["duplicate_in_dossier"] += 1
            continue
        seen.add((subject["person_key"], cid))
        rows.append({
            "doc_id": entry["doc_id"],
            "company_key": cid,
            "company_name": cname,
            "person_key": subject["person_key"],
            "name_clean": subject["name_clean"],
            "surname": subject.get("surname", ""),
            "given": subject.get("given", ""),
            "role": role,
            "is_former": "1" if m.group("former") else "",
            "year": year,
            "region": entry.get("region", ""),
            "country": entry.get("country", ""),
            "source_genre": "person_dossier",
            # Columns the merge expects from every genre. This stage has no
            # abbreviated note to resolve (the company name is written out) and
            # no board-list trigger (the line is the record), so both are empty
            # rather than absent — `build_network` indexes them positionally.
            "annotation": "",
            "sector": entry.get("sector", ""),
            "anchor_type": "person_entry",
            "source_ref": entry.get("name_listed", "")[:120],
            "match_method": method,
            "company_raw": name,
            "line_raw": m.group(0).strip()[:200],
        })
        why["kept"] += 1
    return rows, why


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=0,
                    help="print a random sample of kept rows with their line")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    companies = load("companies.csv")
    if not companies:
        raise SystemExit("run: python3 src/build_network.py first")
    RA.PLACE_FOLD.update(RA.fold(p) for p in PLACES)
    index = RA.build_index(companies)
    by_first: dict[str, list[int]] = defaultdict(list)
    for i, (_cid, _name, toks) in enumerate(index):
        for t in set(RA.content(toks) or toks):
            by_first[t[:RA.MIN_TOKEN]].append(i)

    docs = [d for d in load("documents.csv") if d.get("entry_type") == "person"]
    rows: list[dict] = []
    why: Counter = Counter()
    subjects, no_subject = 0, []
    for d in docs:
        subject = subject_of(d)
        if not subject:
            no_subject.append(d.get("name_listed", ""))
            continue
        subjects += 1
        text = read_text(d["doc_id"])
        if not text:
            continue
        got, w = extract(d, text, subject, index, by_first)
        rows.extend(got)
        why.update(w)

    cols = ["doc_id", "company_key", "company_name", "person_key", "name_clean",
            "surname", "given", "role", "is_former", "year", "source_ref",
            "annotation", "region", "country", "sector", "anchor_type",
            "source_genre", "match_method", "company_raw", "line_raw"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(rows):,} rows", file=sys.stderr)

    docs_hit = len({r["doc_id"] for r in rows})
    print(f"\n{len(docs)} person entries, {subjects} with a usable subject "
          f"({len(no_subject)} refused), {docs_hit} yielding a tie",
          file=sys.stderr)
    print(f"people {len({r['person_key'] for r in rows}):,}, "
          f"companies {len({r['company_key'] for r in rows}):,}, "
          f"dated {sum(1 for r in rows if r['year']):,}", file=sys.stderr)
    for k, n in why.most_common(10):
        print(f"  {k:28} {n:5,}", file=sys.stderr)
    if no_subject[:5]:
        print(f"  refused subjects e.g. {no_subject[:4]}", file=sys.stderr)

    if args.audit and rows:
        random.seed(args.seed)
        print(f"\n--- {args.audit} random rows to hand-check ---", file=sys.stderr)
        for r in random.sample(rows, min(args.audit, len(rows))):
            print(f"\n  {r['name_clean']}  --[{r['role']}]-->  {r['company_name']}"
                  f"  ({r['year'] or 'no year'}, {r['match_method']})",
                  file=sys.stderr)
            print(f"    raw: {r['line_raw'][:150]}", file=sys.stderr)


if __name__ == "__main__":
    main()
