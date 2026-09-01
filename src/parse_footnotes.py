"""The compiler's own biographical footnotes - MEASURED, NOT MERGED.

    python3 src/parse_footnotes.py            # -> affiliations_footnote.csv
    python3 src/parse_footnotes.py --audit 20 # print rows for hand-checking

**Read this before using the output.** This module is not part of the pipeline.
`build_network.py` does not read its CSV and no flag switches it on. A 15-row
hand audit against source text put precision at 8-9 of 15 (~55-60%), against
the 90-97% the six shipped genres measure, so it is not merged. The two failure
classes, and why they are not fixed here, are recorded in METHODOLOGY §2b
("A genre measured and left out"). Run it to reproduce that number; do not
treat `affiliations_footnote.csv` as dataset.

Wherever a board list names someone the compiler knows about, he attaches a
numbered footnote giving that man's career. The footnote's shape is fixed: the
name, his life dates in parentheses, a colon, and then the career in prose.

    Paul Bayard (1852-1931) : polytechnicien, ingénieur aux forges de Pompey,
    directeur des Forges et clouteries réunies à Charleville, puis des Forges
    de Montataire, il part en Russie en 1881 …

    Jean Charmetant (1880-1959) : … Commissaire aux comptes de la Rurale
    tunisienne, de la Société de colonisation de l'Oued-Ramel, de la Société
    de Djimla …

This is the same genre as stage 3e and none of the five earlier parsers can
read it. `parse_ties.py` wants a board list under a firm heading; here the
heading is a person and the text is prose. `parse_prose.py` wants an inline
`M.`/`MM.` marker; the person is the footnote's own header and is never
re-named. `parse_biographies.py` has exactly the right machinery — entry
segmentation, then role-governed company phrases resolved against the company
list — but its entry header is the *dictionary* form, an all-capitals surname
with the forename parenthesised, and it needs three bracketed `[Administrateur`
blocks before it will look at a document at all. The footnote form is
mixed-case with **dates** in the parentheses, and carries no brackets.

So this stage is deliberately thin: it contributes one header pattern and two
rejection rules, and borrows everything else from stage 3e.

**Why the dates are the whole trick.** A mixed-case line ending in a colon is
ordinary prose punctuation and matching it alone would segment on every
sentence. Requiring a four-digit year inside the parentheses is what makes the
pattern the compiler's footnote convention rather than a guess: 8,872 headers
across the corpus. The convention is real; the audit's finding is that the
residue of non-persons sharing it is large enough to matter, and that the
company side leaks role words and institutions.

Output carries `source_genre = "footnote"` so that it can never be mistaken for
stage 3e's `biographical` label, whose ~93% precision was measured on a
different source.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parse_biographies as B  # noqa: E402
from common import ensure_dir  # noqa: E402
from names import parse_person_name  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(PROC, "affiliations_footnote.csv")

# The footnote header: a mixed-case name, life dates in parentheses, a colon.
# The year is the load-bearing part - see the module docstring.
FOOTNOTE_ENTRY_RE = re.compile(
    r"(?m)^[ \t]*(?P<name>[A-ZÉÈÀÂÎÔÛÇ][^\n:()]{2,52}?)\s*"
    r"\(\s*(?P<dates>[^)\n]{0,30}?\b(?:1[6-9]\d\d|20\d\d)\b[^)\n]{0,26})\)\s*:")

# Headers that have the footnote's shape without being a person. The compiler
# writes his decoration lines the same way — "Chevalier de la Légion d'honneur
# (1911) :" — and `parse_person_name` will happily read "Chevalier" as a
# surname. Deliberately narrow: an earlier draft of this rule included
# `mari[eé]` for "Marié à …" and rejected Marie-Antoinette Boullard-Devé and
# every other real person with Marie in their name.
NOT_A_PERSON_RE = re.compile(
    r"^(?:grand[- ])?(?:chevalier|officier|commandeur|"
    r"m[eé]daill|croix|palmes|promotion|d[eé]cor)"
    r"|\b(?:l[eé]gion\s+d['’]honneur|m[eé]rite\s+(?:agricole|maritime)|"
    r"officier\s+d['’]acad[eé]mie|annuaire|bulletin)\b",
    re.I)

# A role governing a *function of the state* rather than a company: "directeur
# de l'agriculture", "chef du service des mines". The company resolver matches
# on content words, so "l'agriculture" found a "Cie d'agriculture" and turned a
# colonial administrator into one of its directors. These are the offices that
# recur; a phrase this generic is dropped rather than guessed at.
PUBLIC_OFFICE_RE = re.compile(
    r"(?i)^(?:l['’]|la\s+|le\s+|les\s+|du\s+|de\s+la\s+|des\s+)?"
    r"(?:agriculture|finances?|budget|tr[eé]sor|douanes?|imp[oô]ts?|"
    r"travaux\s+publics?|enseignement|instruction|sant[eé]|hygi[eè]ne|"
    r"marine|guerre|air|colonies?|justice|int[eé]rieur|affaires\s+\w+|"
    r"personnel|contentieux|contr[oô]le|comptabilit[eé]|"
    r"cabinet|secr[eé]tariat|administration|gouvernement|"
    r"service[s]?(?:\s+\w+)?|succursale|agence|exploitation|"
    r"r[eé]gion|province|territoire|commune|ville|port)\b\s*$")

MAX_ENTRY_CHARS = 3000   # a footnote longer than this lost its boundary
MIN_NAME_WORDS = 2       # "Bayard :" alone is not a header this stage trusts


def is_person_header(raw: str) -> bool:
    """Whether a footnote header names a person rather than a decoration."""
    if NOT_A_PERSON_RE.search(raw):
        return False
    if len(re.findall(r"[^\W\d_]{2,}", raw)) < MIN_NAME_WORDS:
        return False
    return bool(parse_person_name(raw)["surname"])


def entries(text: str):
    """Yield `(header, body)` for each footnote block in one document."""
    heads = list(FOOTNOTE_ENTRY_RE.finditer(text))
    for i, h in enumerate(heads):
        raw = h.group("name").strip()
        if not is_person_header(raw):
            continue
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[h.end():min(end, h.end() + MAX_ENTRY_CHARS)]
        yield raw, body


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=0,
                    help="print this many random rows for hand-checking")
    args = ap.parse_args()

    def load(name):
        with open(os.path.join(PROC, name), encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    docs = load("documents.csv")
    index = B.build_index(load("companies.csv"))
    by_first: dict[str, list[int]] = collections.defaultdict(list)
    for i, (_, _, toks) in enumerate(index):
        for t in set(B.content(toks) or toks):
            by_first[t[:2]].append(i)

    rows, reasons, dropped = [], collections.Counter(), collections.Counter()
    hit_docs = []
    for doc in docs:
        text = B.read_text(doc["doc_id"])
        if not text:
            continue
        n_before = len(rows)
        for person_raw, body in entries(text):
            parsed = parse_person_name(person_raw)
            for role, cname in B.affiliations_in(body):
                if PUBLIC_OFFICE_RE.match(cname.strip()):
                    dropped["public_office"] += 1
                    continue
                cid, resolved, method = B.resolve(cname, index, by_first)
                reasons[method] += 1
                if not cid:
                    continue
                rows.append({
                    "doc_id": doc["doc_id"],
                    "company_key": cid,
                    "company_name": resolved,
                    "person_key": parsed["person_key"],
                    "name_clean": parsed["name_clean"],
                    "surname": parsed["surname"],
                    "given": parsed["given"],
                    "role": role,
                    "year": "",
                    "source_ref": doc["name_normalised"] or doc["name_listed"],
                    "annotation": cname[:120],
                    "region": doc.get("region", ""),
                    "country": doc.get("country", ""),
                    "sector": doc.get("sector", ""),
                    "anchor_type": "footnote_entry",
                    "trigger": "footnote",
                    "parse_note": parsed.get("parse_note", ""),
                    "member_raw": person_raw,
                    "match_method": method,
                    "source_genre": "footnote",
                })
        if len(rows) > n_before:
            hit_docs.append((len(rows) - n_before,
                             doc["name_normalised"] or doc["name_listed"]))

    ensure_dir(PROC)
    fields = list(rows[0].keys()) if rows else ["doc_id"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(rows):,} ties, "
          f"{len({r['person_key'] for r in rows}):,} people, "
          f"{len({r['company_key'] for r in rows}):,} firms", file=sys.stderr)
    print(f"  resolution: {reasons.most_common(6)}", file=sys.stderr)
    print(f"  dropped as a public office: {dropped['public_office']:,}",
          file=sys.stderr)
    for n, name in sorted(hit_docs, reverse=True)[:6]:
        print(f"  {n:7,}  {name[:62]}", file=sys.stderr)

    if args.audit and rows:
        rng = random.Random(5)
        for r in rng.sample(rows, min(args.audit, len(rows))):
            print(f"\n{r['name_clean']} = {r['role']} of {r['company_name']}"
                  f"\n   raw phrase: {r['annotation']}"
                  f"\n   method: {r['match_method']}  doc: {r['doc_id'][:48]}")


if __name__ == "__main__":
    main()
