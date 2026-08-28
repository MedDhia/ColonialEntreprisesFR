"""Stage 3e - biographical dictionaries.

    python3 src/parse_biographies.py   # -> data/processed/affiliations_biographical.csv

*Qui êtes-vous ? 1924*, *Légion d'honneur en Indochine* and their kind are
person-indexed: the entry is a name in capitals, followed by fielded prose,
and the affiliations sit in a bracketed block the compiler added:

    ACCAMBRAY (Léon), député [1914-1932] et CG Aisne
    125, av. de Paris à Saint-Mandé. …
    [Administrateur : Compagnie céramique française (nommé à la constitution,
    mai 1921), Compagnie africaine de commerce, d'industrie et d'agriculture …]

Three parsers already exist and none can read this. `parse_ties.py` wants a
board list under a firm heading; here the heading is a *person*.
`parse_person_index.py` wants numbered references into a companion list; here
the companies are named. `parse_prose.py` wants an inline `M.`/`MM.` marker;
here the person is the entry header and is never re-named.

What this stage adds is **person-scoped segmentation**: the document is split
into entries at the capitalised surname headers, and every role construction
found inside an entry is attributed to that entry's person. The company names
are then resolved with the prefix matcher from `resolve_annotations`, which
was audited at ~94% on the same kind of abbreviated name.

Two forms are read, both common in the brackets:

    [Administrateur : Company A (…), Company B]        a labelled list
    [administrateur de la Société fiduciaire … et des Anc. Éts A. G. Rozis]

Bracketed blocks that are running biography rather than affiliation — "il
entre au service de la Banque de Paris, d'abord président des Constructions
électriques de France" — are read only where a role word governs a company
name directly. A narrative mentioning an employer is not a directorship.

Output is a separate file with `source_genre = "biographical"`, not merged by
default.
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

from common import clean_text, strip_accents  # noqa: E402
from parse_person_index import parse_index_name  # noqa: E402
from parse_ties import canonical_role  # noqa: E402
from resolve_annotations import build_index, content, resolve, tokens  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
TEXT = os.path.join(ROOT, "data", "text")
OUT = os.path.join(PROC, "affiliations_biographical.csv")

# An entry header: a capitalised surname followed by the forename in
# parentheses, at line start. This is the genre's defining shape.
ENTRY_RE = re.compile(
    r"(?m)^(?P<name>[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ'’\- ]{2,44}\s*\([^)\n]{1,44}\))")

ROLE = (r"administrateur(?:\s+d[ée]l[ée]gu[ée])?|pr[ée]sident|vice-pr[ée]sident|"
        r"directeur(?:\s+g[ée]n[ée]ral)?|g[ée]rant|censeur|"
        r"commissaire\s+aux\s+comptes|membre\s+du\s+conseil")
# "Administrateur : A, B, C" - a labelled list.
LABELLED_RE = re.compile(rf"\b(?P<role>{ROLE})s?\s*:\s*(?P<list>[^\]\[]{{4,600}})", re.I)
# "administrateur de la Société X et des Éts Y" - a governed noun phrase.
GOVERNED_RE = re.compile(
    rf"\b(?P<role>{ROLE})\s+(?:de\s+la|de\s+l['’]|du|des|de)\s+"
    rf"(?P<name>[^,;.\]\[]{{4,90}})", re.I)

# A capitalised headline has the same shape as an entry header: "UNE ROSETTE
# BIEN PLACÉE (L...)" was read as a person. Real surnames do not contain these.
HEADLINE_WORDS = {
    "une", "un", "bien", "pour", "dans", "avec", "sur", "tres", "plus", "tout",
    "toute", "leur", "notre", "votre", "cette", "quel", "quelle", "encore",
    "apres", "avant", "sans", "sous", "chez", "entre", "vers", "depuis",
    "placee", "place", "grand", "grande", "petit", "petite", "nouveau",
}
MIN_BLOCKS = 3          # documents with fewer are not this genre
MAX_ENTRY_CHARS = 9000  # an entry longer than this lost its boundary


def read_text(doc_id: str) -> str | None:
    path = os.path.join(TEXT, f"{doc_id}.txt.gz")
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read().replace("\x0c", "\n")
    except OSError:
        return None


def split_list(raw: str) -> list[str]:
    """Split a company list on commas that are not inside brackets."""
    out, depth, cur = [], 0, []
    for ch in raw:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",;" and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [clean_text(re.sub(r"\([^)]*\)", " ", p)).strip(" .,;:")
            for p in out if p.strip()]


def entries(text: str):
    starts = [(m.start(), m.group("name")) for m in ENTRY_RE.finditer(text)]
    for (a, name), (b, _) in zip(starts, starts[1:] + [(len(text), "")]):
        body = text[a:b]
        if len(body) > MAX_ENTRY_CHARS:
            continue
        caps = name.split("(")[0]
        words = {strip_accents(w).lower() for w in re.findall(r"[^\W\d_]{2,}", caps)}
        if words & HEADLINE_WORDS:
            continue
        yield clean_text(name), body


def affiliations_in(body: str):
    """Yield (role, company_name) from one entry."""
    for m in LABELLED_RE.finditer(body):
        role = canonical_role(m.group("role")) or "administrateur"
        for name in split_list(m.group("list")):
            if len(name) >= 4:
                yield role, name
    for m in GOVERNED_RE.finditer(body):
        role = canonical_role(m.group("role")) or "administrateur"
        name = clean_text(re.sub(r"\([^)]*\)", " ", m.group("name"))).strip(" .,;:")
        if len(name) >= 6:
            yield role, name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=0)
    args = ap.parse_args()

    def load(name):
        with open(os.path.join(PROC, name), encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    docs = load("documents.csv")
    index = build_index(load("companies.csv"))
    by_first: dict[str, list[int]] = defaultdict(list)
    for i, (_, _, toks) in enumerate(index):
        for t in set(content(toks) or toks):
            by_first[t[:2]].append(i)

    rows, reasons, audit, hit_docs = [], Counter(), [], []
    for doc in docs:
        text = read_text(doc["doc_id"])
        if not text or len(re.findall(r"\[\s*(?:administrateur|pr[ée]sident|"
                                      r"directeur|g[ée]rant|censeur)", text,
                                      re.I)) < MIN_BLOCKS:
            continue
        n_before = len(rows)
        for person_raw, body in entries(text):
            parsed = parse_index_name(person_raw)
            if not parsed["person_key"]:
                continue
            for role, cname in affiliations_in(body):
                cid, resolved, method = resolve(cname, index, by_first)
                if not cid:
                    reasons[method] += 1
                    continue
                reasons[method] += 1
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
                    "anchor_type": "biographical_entry",
                    "trigger": "biographical",
                    "parse_note": parsed.get("parse_note", ""),
                    "member_raw": person_raw,
                    "match_method": method,
                    "source_genre": "biographical",
                })
                audit.append((person_raw, cname, resolved, method))
        if len(rows) > n_before:
            hit_docs.append((len(rows) - n_before,
                             doc["name_normalised"] or doc["name_listed"]))

    if args.audit:
        random.seed(9)
        for p, raw, res, m in random.sample(audit, min(args.audit, len(audit))):
            print(f"{p[:26]:<26} {raw[:34]:<34} -> {res[:40]:<40} [{m}]")
        return

    fields = ["doc_id", "company_key", "company_name", "person_key", "name_clean",
              "surname", "given", "role", "year", "source_ref", "annotation",
              "region", "country", "sector", "anchor_type", "trigger",
              "parse_note", "member_raw", "match_method", "source_genre"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(rows):,} ties, "
          f"{len({r['person_key'] for r in rows}):,} people, "
          f"{len({r['company_key'] for r in rows}):,} firms", file=sys.stderr)
    print("  by method/reason:", dict(reasons.most_common(6)), file=sys.stderr)
    for n, title in sorted(hit_docs, reverse=True)[:6]:
        print(f"    {n:>5}  {title[:58]}", file=sys.stderr)


if __name__ == "__main__":
    main()
