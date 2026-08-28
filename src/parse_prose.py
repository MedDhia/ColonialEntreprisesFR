"""Stage 3c - board changes reported in running prose.

    python3 src/parse_prose.py    # -> data/processed/affiliations_prose.csv

`parse_ties.py` only fires on a structured list marker: a heading in capitals,
a "Conseil d'administration :" field, a directory entry. That is deliberate -
an earlier version triggered on the bare phrase wherever it appeared and
produced thousands of directors out of ordinary sentences. But most of what
this collection contains is press extracts, and press extracts report boards
in prose:

    Les administrateurs sortants, MM. le comte de Germiny, J. Stewart,
    G. Alberti, J. Alexander, ont été réélus.

There are 1,261 such name-series in documents that currently yield no tie at
all. This stage reads them.

## Why attribution is not the problem here

For a firm dossier the subject company is already known - it is the catalogue
title, which `parse_ties` calls `default_company` and uses for its segments.
So a person found anywhere in the dossier can be attributed with confidence.
The missing piece was never *which firm*; it was only *find the people*.

## Precision, which is the whole risk

Every pattern here requires **three** things together, because any one alone
is a licence to invent directors:

1. an explicit person marker - `MM.`, `M.`, or an appointment verb;
2. an explicit role word within the same clause;
3. every candidate name passing `_fragment_is_namelike`, the same shape test
   the structured parser uses.

Two further guards matter. A role followed by "de la Société X" names someone
else's board, so the tie is dropped unless X is the segment's own company -
"M. Dupont, président de la Banque de Paris" inside a Moroccan mining dossier
is evidence about the Banque de Paris, not about the mine. And a match
overlapping a source citation is discarded, since a newspaper's own masthead
sits in exactly the same shape as a name list.

Output is a **separate file** with `source_genre = "prose"` and its own
`trigger` values, so this evidence can be excluded wholesale. Measured
precision is reported by `--audit`, which prints matches with their source
context for hand-checking, and `checks.py` pins the pattern behaviour on
worked cases from the corpus.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import random
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FORENAMES, clean_text, strip_accents  # noqa: E402
from names import (DESCRIPTOR_RE, looks_like_org, org_key,  # noqa: E402
                   parse_person_name)
from parse_ties import (  # noqa: E402
    CITATION_RE, PROC_DIR as PROC, _fragment_is_namelike, _split_names,
    build_segments, canonical_role, is_annuaire_doc, normalise_org_name,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = os.path.join(ROOT, "data", "text")
OUT = os.path.join(PROC, "affiliations_prose.csv")

ROLE_WORD = (r"administrateur(?:s)?(?:[- ]d[ée]l[ée]gu[ée](?:s)?)?|"
             r"pr[ée]sident(?:s)?|vice-pr[ée]sident(?:s)?|"
             r"directeur(?:s)?(?:\s+g[ée]n[ée]ral(?:e)?(?:s|ux)?)?|"
             r"g[ée]rant(?:s)?|censeur(?:s)?|commissaire(?:s)?\s+aux\s+comptes|"
             r"membre(?:s)?\s+du\s+conseil")
# A run of names: "MM. A, B et C" or "M. X".
#
# The lazy quantifier must have a terminator or it matches its own minimum:
# "sous la présidence de M. Albert Thomas" yielded the name "Alb". Every
# pattern below therefore ends the run at a clause delimiter or at the
# construction that follows it.
NAMES = r"(?P<names>(?:MM\.|M\.|Messieurs)\s*[^.;:]{3,240}?)"
NAMES_TO_DELIM = (r"(?:MM\.|M\.|Messieurs)\s*(?P<names>[^.;:]{3,240}?)"
                  r"(?=\s*(?:[.;:]|,\s*(?:qui|qu[i']|dont|qui\s)|$))")

# Decorations and honours sit in apposition exactly where a name does:
# "M. Antoine Nunzi, commandeur de la Légion d'honneur, président".
DECORATION_RE = re.compile(
    r"^(?:grand[- ])?(?:commandeur|chevalier|officier|grand[- ]croix|"
    r"m[ée]daill[ée]|titulaire|d[ée]cor[ée])\b|"
    r"\b(?:l[ée]gion\s+d['’]honneur|m[ée]rite\s+agricole|palmes\s+acad[ée]miques|"
    r"croix\s+de\s+guerre|ordre\s+du|dragon\s+d['’]annam)\b", re.I)

PATTERNS: list[tuple[str, str, str]] = [
    # "MM. A, B et C, administrateurs" / "..., ont été élus administrateurs"
    ("prose_role_after",
     rf"{NAMES}\s*,\s*(?P<role>{ROLE_WORD})\b", ""),
    # "ont été nommés administrateurs : MM. A, B"
    ("prose_appointed_before",
     rf"(?:ont|a)\s+été\s+(?:nommé|élu|réélu|appelé|désigné)(?:s|es)?\s+"
     rf"(?P<role>{ROLE_WORD})\s*[:,]?\s*{NAMES}", ""),
    # "MM. A, B ont été élus administrateurs" / "... ont été réélus"
    ("prose_appointed_after",
     rf"(?:MM\.|M\.|Messieurs)\s*(?P<names>[^.;:]{{3,240}}?)\s*,?\s*"
     rf"(?:ont|a)\s+été\s+(?:nommé|élu|réélu|appelé|désigné)(?:s|es)?"
     rf"(?:\s+(?P<role>{ROLE_WORD}))?", "administrateur"),
    # "Les administrateurs sortants, MM. A, B, C"
    ("prose_outgoing",
     rf"(?:les\s+)?(?P<role>{ROLE_WORD})\s+sortants?\s*,\s*{NAMES}", ""),
    # "sous la présidence de M. X" / "présidée par M. X"
    ("prose_presidency",
     rf"(?:sous\s+la\s+pr[ée]sidence\s+de|pr[ée]sidée?\s+par)\s+{NAMES_TO_DELIM}",
     "president"),
    # "nomination de M. X comme administrateur"
    ("prose_nomination",
     rf"nomination\s+de\s+(?:MM\.|M\.|Messieurs)\s*(?P<names>[^.;:]{{3,240}}?)\s+"
     rf"(?:comme|en\s+qualit[ée]\s+de|aux\s+fonctions\s+de)\s+"
     rf"(?P<role>{ROLE_WORD})", ""),
]
COMPILED = [(name, re.compile(rx, re.I), default) for name, rx, default in PATTERNS]

# "président de la Société X" - a role at somebody else's firm.
OTHER_FIRM_RE = re.compile(
    r"\s+(?:de|du|de\s+la|des)\s+(?:la\s+)?"
    r"(?:soci[ée]t[ée]|compagnie|banque|cr[ée]dit|comptoir|[ée]tablissements|union|"
    r"omnium|syndicat|caisse|office|groupe)\b[^.;]{0,60}", re.I)

MAX_NAMES_CHARS = 240

# A non-compete undertaking uses the role words in the negative: "s'interdisent
# de fonder, acquérir, exploiter ou diriger comme gérants, directeurs". Read
# positively it appoints the signatories to jobs they are promising not to take.
NEGATION_RE = re.compile(
    r"s['’]interdi|interdiction\s+de|ne\s+pourra(?:ient)?\s+|"
    r"s['’]engage(?:nt)?\s+à\s+ne\s+pas|renonce(?:nt)?\s+à", re.I)

# Street addresses sit inside member runs: "demeurant à Paris, 10, rue de
# Laborde" yielded a director called "rue de Laborde".
ADDRESS_RE = re.compile(
    r"^(?:rue|avenue|av\.|boulevard|bd\.?|place|quai|impasse|cours|all[ée]e|"
    r"faubourg|route|chemin|villa|cit[ée]|square|immeuble|domicili[ée]|demeurant)\b",
    re.I)

# Presiding a meeting is not holding a board seat. "sous la présidence de
# M. Louis Martin, maire" is the mayor chairing an AGM.
BOARD_PRESIDENCY_RE = re.compile(r"^\W{0,12}pr[ée]sident\b[^.;]{0,20}\bdu\s+conseil", re.I)

# names.DESCRIPTOR_RE is anchored with ^, so .search() on a member run never
# fires mid-string: "Fouque Laurent, conseiller général, président" passed
# straight through the occupation guard. This is the same vocabulary,
# unanchored, for testing *inside* a run.
DESCRIPTOR_INLINE_RE = re.compile(
    r"\b(?:ing[ée]nieur|industriel|n[ée]gociant|banquier|avocat|architecte|"
    r"entrepreneur|propri[ée]taire|colon|planteur|agriculteur|commer[cç]ant|"
    r"docteur|d[ée]put[ée]|s[ée]nateur|conseiller|juge|tr[ée]sorier|doyen|"
    r"pharmacien|notaire|courtier|armateur|imprimeur|libraire|fabricant|"
    r"capitaine|lieutenant|colonel|g[ée]n[ée]ral|inspecteur|receveur|percepteur|"
    r"gouverneur|pr[ée]fet|maire|consul|ministre|agent\s+maritime)\b", re.I)


def read_text(doc_id: str) -> str | None:
    path = os.path.join(TEXT, f"{doc_id}.txt.gz")
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read().replace("\x0c", "\n")
    except OSError:
        return None


def other_firm_after_role(text: str, role_end: int, own_company: str) -> bool:
    """True when the role is held at a firm other than this segment's."""
    m = OTHER_FIRM_RE.match(text, role_end)
    if not m:
        return False
    named = clean_text(m.group(0))
    if not own_company:
        return True
    a, b = org_key(named), org_key(own_company)
    # Substring either way: the prose form is usually shorter than the
    # catalogue form ("la Banque de l'Indochine" vs its full legal name).
    return not (a and b and (a in b or b in a))


def names_from(raw: str) -> list[str]:
    raw = re.sub(r"^(?:MM\.|M\.|Messieurs)\s*", "", clean_text(raw)).strip(" ,;:.")
    if len(raw) > MAX_NAMES_CHARS:
        return []
    out = []
    for part in re.split(r"\s*(?:,|\bet\b)\s*", raw):
        for frag in _split_names(part):
            frag = frag.strip(" ,;:.")
            if not frag or not _fragment_is_namelike(frag) or looks_like_org(frag):
                continue
            # "commandeur de la Légion d'honneur" sits where a name sits.
            if (DECORATION_RE.search(frag) or DESCRIPTOR_RE.match(frag)
                    or ADDRESS_RE.match(frag) or NEGATION_RE.search(frag)):
                continue
            # A comma inside a compound forename splits it off as its own
            # person: "M. CASSOUTE Paul, Léon" yielded a director called
            # "Léon". A lone known forename is never a surname here.
            toks = frag.split()
            if len(toks) == 1 and strip_accents(toks[0]).lower().strip(".") in FORENAMES:
                continue
            out.append(frag)
    return out


def _is_plural(role_raw: str) -> bool:
    """Plural role word -> the whole run holds it; singular -> only the last."""
    return bool(re.search(r"(?:s|x)\s*$", role_raw.strip()))


def extract(text: str, company: str, citation_spans: list[tuple[int, int]]):
    """Yield (names, role, trigger, matched_text) for one segment."""
    for trigger, rx, default_role in COMPILED:
        for m in rx.finditer(text):
            # A newspaper masthead inside a citation has the shape of a list.
            if any(s <= m.start() < e for s, e in citation_spans):
                continue
            gd = m.groupdict()
            role_raw = gd.get("role") or default_role
            if not role_raw:
                continue
            # A negated clause in the same sentence inverts the whole match.
            if NEGATION_RE.search(text[max(0, m.start() - 160):m.end() + 40]):
                continue
            if trigger == "prose_presidency":
                # Accept only "présidence de M. X, président du conseil ...".
                # Without that, the person is chairing the meeting and may be
                # a mayor, a prefect or the auditor.
                if not BOARD_PRESIDENCY_RE.match(text[m.end():m.end() + 60]):
                    continue
            if gd.get("role"):
                # An occupation between the name and the role means the role
                # is not the one the name holds at this firm: "M. Willot,
                # inspecteur général des Postes, président" presides a session.
                between = gd["names"]
                if DESCRIPTOR_INLINE_RE.search(
                        re.sub(r"^(?:MM\.|M\.|Messieurs)\s*", "", clean_text(between))):
                    continue
            if gd.get("role"):
                if other_firm_after_role(text, m.end("role"), company):
                    continue
            people = names_from(gd["names"])
            if not people:
                continue
            # "MM. Meunier, Guibal, ..., Billiard, président" - a *singular*
            # role after a list names only the last person. Reading it as the
            # whole list made eleven presidents of one company.
            if len(people) > 1 and gd.get("role") and not _is_plural(role_raw):
                people = people[-1:]
            yield (people, canonical_role(role_raw) or "administrateur", trigger,
                   clean_text(m.group(0))[:200])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=0,
                    help="print N random matches with context and exit")
    ap.add_argument("--limit", type=int, default=0, help="stop after N documents")
    args = ap.parse_args()

    with open(os.path.join(PROC, "documents.csv"), encoding="utf-8", newline="") as fh:
        docs = list(csv.DictReader(fh))

    rows: list[dict] = []
    audit: list[tuple[str, str, str, str]] = []
    seen_docs = 0
    for doc in docs:
        text = read_text(doc["doc_id"])
        if not text:
            continue
        seen_docs += 1
        if args.limit and seen_docs > args.limit:
            break
        annuaire = is_annuaire_doc(doc, text[:6000])
        default_company = doc["name_normalised"] or doc["name_listed"]
        if doc["entry_type"] != "company":
            default_company = ""
        segments = build_segments(text, annuaire, default_company)
        for seg in segments:
            comp = clean_text(seg["company"])
            if not comp or not re.search(r"[A-Za-zÀ-ÿ]{3}", comp):
                continue
            ckey = org_key(comp)
            if not ckey:
                continue
            body = seg["text"]
            citations = [(mm.start(), mm.end()) for mm in CITATION_RE.finditer(body)]
            for people, role, trigger, matched in extract(body, comp, citations):
                for raw in people:
                    parsed = parse_person_name(raw)
                    if not parsed["person_key"]:
                        continue
                    rows.append({
                        "doc_id": doc["doc_id"],
                        "company_key": ckey,
                        "company_name": normalise_org_name(comp),
                        "person_key": parsed["person_key"],
                        "name_clean": parsed["name_clean"],
                        "surname": parsed["surname"],
                        "given": parsed["given"],
                        "role": role,
                        "year": seg.get("year", ""),
                        "source_ref": seg.get("source_ref", ""),
                        "annotation": "",
                        "region": doc.get("region", ""),
                        "country": doc.get("country", ""),
                        "sector": doc.get("sector", ""),
                        "anchor_type": seg.get("anchor", ""),
                        "trigger": trigger,
                        "parse_note": parsed.get("parse_note", ""),
                        "member_raw": raw,
                        "source_genre": "prose",
                    })
                    if len(audit) < 4000:
                        audit.append((raw, role, comp, matched))

    if args.audit:
        random.seed(5)
        for raw, role, comp, matched in random.sample(audit, min(args.audit, len(audit))):
            print(f"\nPERSON  {raw}\nROLE    {role}\nFIRM    {comp[:64]}\nTEXT    {matched}")
        return

    fields = ["doc_id", "company_key", "company_name", "person_key", "name_clean",
              "surname", "given", "role", "year", "source_ref", "annotation",
              "region", "country", "sector", "anchor_type", "trigger",
              "parse_note", "member_raw", "source_genre"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(rows):,} ties, "
          f"{len({r['person_key'] for r in rows}):,} people, "
          f"{len({r['company_key'] for r in rows}):,} firms, "
          f"{len({r['doc_id'] for r in rows}):,} documents", file=sys.stderr)
    print("  by trigger:", dict(Counter(r["trigger"] for r in rows).most_common()),
          file=sys.stderr)
    print("  by role:", dict(Counter(r["role"] for r in rows).most_common(6)),
          file=sys.stderr)


if __name__ == "__main__":
    main()
