"""Stage 3b - the person-indexed sources the firm-dossier parser cannot see.

    python3 src/parse_person_index.py     # -> data/processed/affiliations_person_index.csv

`parse_ties.py` reads one genre: the firm dossier, where a board appears as
*"Conseil d'administration : MM. X, Y, Z"*. The collection contains a second
genre it is structurally blind to — the **inverted index**, where the entry is
a person and the list is of companies:

    Achard (Georges-P.), 107 (dga BAO), 207 (Bq comm. afr.),
        238 (Créd. fonc. Ouest-Afric.), 1776 (Cult. Diakandapé).

The numbers are not page references. They key into a companion document in the
same annuaire that lists the companies in numbered order:

    107. Banque de l'Afrique occidentale.

So the pair is a complete, resolvable affiliation dataset. `Annuaire Desfossés
1956` alone yields ~17,000 person-company links — a quarter again on top of
everything the dossier parser finds — and produced exactly zero rows before
this stage existed.

## The trap this parser is built around

Entries carry bracketed biographical notes, and those brackets contain
numbers:

    Abinal (Patrice)[1883-1961][ing.-conseil, anc. adm. Soc. d'études …], 1613 (…)

`1883` and `1961` are life dates. They are also both valid company numbers in
the 22-2290 range, so a naive scan reads them as directorships and produces
ties that look perfectly plausible and never happened. There are 2,628 numbers
inside brackets in this one document. **Bracketed spans are stripped before
any number is read**, and a reference is only accepted in list position -
after a comma, followed by a gloss or a delimiter.

## How the result is checked rather than asserted

Most references carry a gloss: `107 (dga BAO)`. The gloss is the compiler's
own abbreviation of the company name, so it is an independent statement of
what the number means. The parser scores every glossed reference for token
overlap against the name the key gives, and reports the agreement rate. If the
numbering were misaligned - an off-by-one in the key, a page of the index
belonging to a different annuaire - that rate would collapse. It is the check
that this stage is reading the source correctly, and `checks.py` enforces a
floor on it.

Output has the same schema as `affiliations.csv` plus `source_genre`, so the
two can be concatenated or analysed apart.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import clean_text, plausible_year  # noqa: E402
from names import (PARTICLES, looks_like_org, make_person_key, org_key,  # noqa: E402
                   parse_person_name)
from parse_ties import ROLE_RES  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
TEXT = os.path.join(ROOT, "data", "text")
OUT = os.path.join(PROC, "affiliations_person_index.csv")
REPORT = os.path.join(PROC, "person_index_report.csv")

# A key document lists companies in numbered order; an index document lists
# people each followed by company numbers. Both thresholds are deliberately
# high: this stage should fire on annuaires, not on a dossier that happens to
# contain a numbered list.
MIN_KEY_ENTRIES = 150
MIN_INDEX_ENTRIES = 150

KEY_RE = re.compile(r"^[ \t]*(\d{1,4}(?:/\d+)?)\.[ \t]+(.+?)[ \t]*$", re.M)
# A reference in list position: preceded by a comma or the start of the list,
# and followed by a gloss in parentheses or a list delimiter.
REF_RE = re.compile(r"(?:^|,)\s*(\d{1,4}(?:/\d+)?)\s*(?:\(([^)]*)\))?(?=\s*[,.;]|\s*$)")
MAX_BRACKET_SPAN = 400   # a note longer than this is not a note
ENTRY_START_RE = re.compile(r"(?m)^(?=[A-ZÉÈÀÂÎÔÛÇ][^\n]{0,90}?[,)\]]\s*\d)")
SECTION_RE = re.compile(r"^\s*[A-ZÉÈÀÂÎÔÛÇ]\.?\s*$")


def strip_brackets(text: str) -> str:
    """Remove [...] spans, innermost first, so nesting cannot leave numbers.

    This is the whole safety mechanism of the module: life dates, honours
    codes and editorial notes all live in brackets and all contain digits that
    fall inside the company-number range.

    Newlines inside a span are **kept**. A bracketed note often wraps across
    lines, and collapsing it to a single space welds the next entry onto the
    current one — which is the merge bug this parser exists to avoid, just
    moved somewhere less obvious: the welded entry then collects its
    neighbour's company numbers as if they were its own.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "[":
            out.append(text[i])
            i += 1
            continue
        # Walk to the matching close, tracking depth and refusing to run away.
        depth, k = 1, i + 1
        while k < n and depth and k - i <= MAX_BRACKET_SPAN:
            if text[k] == "[":
                depth += 1
            elif text[k] == "]":
                depth -= 1
            k += 1
        if depth == 0:
            span = text[i:k]
            out.append("\n" * span.count("\n") or " ")
            i = k
        else:
            # Unmatched or implausibly long: drop the bracket character only.
            # This document contains exactly one unmatched '[', and a regex
            # that pairs it with the next ']' far below deletes 87% of the
            # file - which looks like a clean parse of a much smaller source.
            out.append(" ")
            i += 1
    return "".join(out).replace("]", " ")


def read_text(doc_id: str) -> str | None:
    path = os.path.join(TEXT, f"{doc_id}.txt.gz")
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()


NAME_TAIL_RE = re.compile(r"\s*\((?:en\s+liquid[^)]*|ex-[^)]*)\)\s*$", re.I)

# Abbreviations that end in a full stop and are followed by a capital, so a
# naive "cut at the first sentence break" turns "Anc. Établissements Ballande"
# into "Anc". Company names in this source are full of them.
ABBREV = {"anc", "anon", "ets", "éts", "et", "cie", "ste", "sté", "soc", "st",
          "mm", "ex", "nouv", "gr", "gén", "gle", "fr", "afr", "ind", "cial",
          "sté", "cons", "int", "nat"}
COMMENT_RE = re.compile(r"\.\s+[A-ZÉÈÀÂÎÔÛÇ]")


def cut_trailing_commentary(name: str) -> str:
    """Drop a trailing editorial sentence, keeping abbreviated names intact.

    Splitting at the first ". Capital" is the obvious rule and it is wrong
    here: company names in this source are full of abbreviations that end in a
    stop, so "Anc. Établissements Ballande" becomes "Anc". The token before
    the stop is checked against the abbreviation list, and a single letter
    (an initial) is never a sentence end either.
    """
    for m in COMMENT_RE.finditer(name):
        if m.start() < 8:
            continue
        word = re.findall(r"[^\W\d_]+", name[:m.start()])
        if word and (word[-1].lower() in ABBREV or len(word[-1]) == 1):
            continue
        return name[:m.start()].rstrip(". ")
    return name.rstrip(". ")


def parse_key(text: str) -> dict[str, str]:
    out = {}
    for num, name in KEY_RE.findall(text):
        # The key carries the compiler's editorial notes in brackets -
        # "[abs. en 1968 par l'UAP]", "[> Saline à Arzew]". They are commentary
        # on the firm's later fate, not part of its name, and carrying them
        # into company_name would split one firm across several nodes.
        name = clean_text(strip_brackets(name))
        name = NAME_TAIL_RE.sub("", name).rstrip(". ")
        name = cut_trailing_commentary(name)
        # Keep the first occurrence: annuaires repeat a number in a
        # cross-reference line, and the first is the definition.
        if name and num not in out:
            out[num] = name
    return out


def split_entries(text: str):
    starts = [m.start() for m in ENTRY_START_RE.finditer(text)]
    for a, b in zip(starts, starts[1:] + [len(text)]):
        chunk = text[a:b]
        if SECTION_RE.match(chunk.split("\n", 1)[0]):
            continue
        yield clean_text(chunk)


def split_name(entry: str) -> tuple[str, str] | tuple[None, None]:
    """Cut the entry at the first reference that is not inside () or []."""
    depth = 0
    for m in re.finditer(r"[()\[\]]|,\s*\d{1,4}(?:/\d+)?\s*[(,.]", entry):
        tok = m.group(0)[0]
        if tok in "([":
            depth += 1
        elif tok in ")]":
            depth = max(0, depth - 1)
        elif depth == 0:
            return entry[:m.start()].strip(), entry[m.start():]
    return None, None


# Abbreviations specific to this annuaire's gloss style. They are checked
# before the shared rules because several are shorter than, and would be
# swallowed by, the general patterns: "comm. cptes" is a statutory auditor,
# not an administrateur, and the shared rule only knows the spelled-out form.
INDEX_ROLE_RULES: list[tuple[str, str]] = [
    (r"\bcomm\.?\s*(?:cptes|c\.?)\b|\bcac\b", "commissaire_aux_comptes"),
    (r"\bpdt\.?-?adm\.?-?dir\.?|\bp\.?-?d\.?-?g\b", "president_directeur_general"),
    (r"\badm\.?-?dir\.?\b|\badm\.?-?d[ée]l\.?\b", "administrateur_delegue"),
    (r"\bv\.?-?pdt\.?\b", "vice_president"),
    (r"\bpdt\.?\b", "president"),
    (r"\bdga\b|\bdir\.?\s*g[ée]n\.?\b", "directeur_general"),
    (r"\bcenseur\b", "censeur"),
    (r"\bg[ée]rant\b", "gerant"),
    (r"\bliquid(?:ateur)?\.?\b", "liquidateur"),
    (r"\bdir\.?\b", "directeur"),
    (r"\bfond(?:ateur)?\.?\b", "fondateur"),
]
INDEX_ROLE_RES = [(re.compile(p, re.I), c) for p, c in INDEX_ROLE_RULES]


INDEX_NAME_RE = re.compile(r"^(?P<surname>[^()]+?)\s*\((?P<given>[^)]*)\)\s*$")
# A whole parenthetical that is commentary rather than the forename, i.e. one
# containing a colon: "(ep. Cecile Burrus : cf. FIT)", "(1898-1993 : assassine)".
# Removing it whole keeps the real "(Given)" parenthesis intact, which cutting
# at the colon alone would not.
INDEX_COMMENTARY_RE = re.compile(r"\s*\([^()]*:[^()]*\)")


def strip_index_commentary(raw: str) -> str:
    """Drop the compiler's commentary from an index entry's name.

    "Andre (Jacques) (ep. Cecile Burrus : cf. FIT)", "Pharaon (Henri)(1898-1993
    : assassine)", "Tavera (Maurice) : 159 (comm. gvt...)". A colon never occurs
    inside a name, on this side of the pipeline any more than on the dossier
    side, so the name ends before it.
    """
    if ":" not in raw:
        return raw
    # Remove a whole parenthetical that is commentary before cutting at the
    # colon, so that a real "(Given)" parenthesis elsewhere survives.
    out = INDEX_COMMENTARY_RE.sub("", raw).split(":")[0].strip(" ,;.([")
    # "Chenut (C.) sic." leaves an editorial marker after the forename
    # parenthesis, which INDEX_NAME_RE requires to be last. Cut back to it.
    if ")" in out and not out.endswith(")"):
        out = out[: out.rindex(")") + 1]
    return out


def parse_index_name(raw: str) -> dict:
    """Parse a `Surname (Given)` entry, which this genre guarantees.

    The general parser must guess which token is the surname, and on
    "Baert (J.)" it guesses wrong - reading "Baert" as the forename and "J."
    as the surname. Every `J.` in the B's then collapses into one node: 148
    distinct people keyed as `j-b`, generating thousands of interlock edges
    between firms that never shared a director. Here the format is known, so
    it is applied rather than inferred.

    A trailing particle belongs to the surname: "Abs (P. d')" is P. d'Abs.
    """
    raw = strip_index_commentary(raw.strip())
    m = INDEX_NAME_RE.match(raw)
    if not m:
        # No parenthesis: the whole string is the surname.
        return {"surname": raw, "given": "", "name_clean": raw,
                "person_key": make_person_key(raw, ""), "parse_note": "index_surname_only"}

    surname = m.group("surname").strip(" ,;.")
    given = m.group("given").strip(" ,;.")

    # "P. d'" -> the particle moves in front of the surname.
    note = "index_surname_paren"
    tokens = given.replace("\u2019", "'").split()
    particles = []
    while tokens and tokens[-1].rstrip("'").lower() in PARTICLES:
        particles.insert(0, tokens.pop())
        note = "index_particle_moved"
    if particles:
        joined = " ".join(particles)
        surname = (f"{joined}{surname}" if joined.endswith("'")
                   else f"{joined} {surname}")
        given = " ".join(tokens)

    name_clean = f"{given} {surname}".strip()
    return {"surname": surname, "given": given, "name_clean": name_clean,
            "person_key": make_person_key(surname, given), "parse_note": note}


def role_of(gloss: str) -> str:
    """Role from the gloss, defaulting to administrateur.

    The default is the document's own claim: this index is headed
    "ADMINISTRATEURS DES SOCIÉTÉS COTÉES", so an unqualified entry is an
    administrateur. Only a gloss that says otherwise overrides it.
    """
    for rx, canon in INDEX_ROLE_RES:
        if rx.search(gloss):
            return canon
    for rx, canon in ROLE_RES:
        if rx.search(gloss):
            return canon
    return "administrateur"


def gloss_agrees(gloss: str, name: str) -> bool | None:
    """Does the compiler's abbreviation match the name the key gives?

    Returns None when there is nothing to compare. Token-prefix matching,
    because the glosses are abbreviations: 'Bq comm. afr.' against 'Banque
    commerciale africaine'.
    """
    g = [t for t in re.findall(r"[^\W\d_]{3,}", gloss.lower()) if len(t) >= 3]
    if not g:
        return None
    n = re.findall(r"[^\W\d_]{3,}", name.lower())
    if not n:
        return None
    for gt in g:
        for nt in n:
            if nt.startswith(gt[:3]) or gt.startswith(nt[:3]):
                return True
    return False


def find_pairs(docs, txcache):
    """Locate (key, index) document pairs belonging to the same annuaire."""
    keys, indexes = {}, {}
    for d in docs:
        text = txcache.get(d["doc_id"])
        if not text:
            continue
        nk = len(KEY_RE.findall(text))
        ni = sum(1 for _ in split_entries(strip_brackets(text)))
        if nk >= MIN_KEY_ENTRIES and nk > ni:
            keys.setdefault(d["name_normalised"], []).append((d, nk))
        elif ni >= MIN_INDEX_ENTRIES:
            indexes.setdefault(d["name_normalised"], []).append((d, ni))

    pairs = []
    for title, idx_docs in indexes.items():
        if title not in keys:
            continue
        key_doc = max(keys[title], key=lambda kv: kv[1])[0]
        for idoc, _ in idx_docs:
            pairs.append((idoc, key_doc, title))
    return pairs, keys, indexes


def parse_pair(idoc, key_doc, title, txcache):
    key = parse_key(txcache[key_doc["doc_id"]])
    body = strip_brackets(txcache[idoc["doc_id"]])
    year = None
    for y in re.findall(r"\b(1[89]\d\d)\b", title):
        if plausible_year(y):
            year = y
    source_ref = title

    rows, org_rows = [], []
    agree = Counter()
    unresolved = Counter()
    for entry in split_entries(body):
        name, rest = split_name(entry)
        if not name:
            continue
        refs = REF_RE.findall(rest)
        if not refs:
            continue
        # Footnote markers and stray digits ride on the end of some names.
        name = re.sub(r"[\s,;:]*\d+\s*$", "", name).strip(" ,;:.-–—")
        # Entry detection occasionally fires on a wrapped continuation line,
        # yielding a fragment like "Cie)". A real entry has a word of three
        # or more letters and balanced parentheses.
        if (len(name) < 3
                or not re.search(r"[^\W\d_]{3,}", name)
                or name.count(")") > name.count("(")):
            continue
        is_org = looks_like_org(name)
        parsed = parse_index_name(name) if not is_org else None
        for num, gloss in refs:
            company = key.get(num)
            if company and len(company) < 3:
                company = None
            if not company:
                unresolved[num] += 1
                continue
            gloss = clean_text(gloss or "")
            ok = gloss_agrees(gloss, company)
            if ok is not None:
                agree["yes" if ok else "no"] += 1
            row = {
                "doc_id": idoc["doc_id"],
                "company_key": org_key(company),
                "company_name": company,
                "role": role_of(gloss),
                "year": year or "",
                "source_ref": source_ref,
                "annotation": gloss,
                "region": idoc.get("region", ""),
                "country": idoc.get("country", ""),
                "sector": idoc.get("sector", ""),
                "anchor_type": "person_index",
                "trigger": "person_index",
                "member_raw": name,
                "entry_number": num,
                "source_genre": "person_index",
            }
            if is_org:
                # The corporate branch keeps the printed name, so it needs the
                # same commentary strip the person branch gets: a few entries
                # are long enough to read as an organisation while actually
                # being a person plus the compiler's biography.
                org_name = strip_index_commentary(name)
                row.update({"member_key": org_key(org_name), "name_clean": org_name})
                org_rows.append(row)
            elif not parsed or not parsed.get("person_key"):
                continue
            else:
                row.update({
                    "person_key": parsed["person_key"],
                    "name_clean": parsed["name_clean"],
                    "surname": parsed["surname"],
                    "given": parsed["given"],
                    "parse_note": parsed.get("parse_note", ""),
                })
                rows.append(row)
    return rows, org_rows, agree, unresolved, len(key)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-agreement", type=float, default=0.80,
                    help="fail if fewer glossed refs than this agree with the key")
    args = ap.parse_args()

    with open(os.path.join(PROC, "documents.csv"), encoding="utf-8", newline="") as fh:
        docs = list(csv.DictReader(fh))

    # Only consider documents big enough to be an annuaire; reading 5,867
    # gzipped files to test 20 of them is the slow way round.
    txcache = {}
    for d in docs:
        path = os.path.join(TEXT, f"{d['doc_id']}.txt.gz")
        if os.path.exists(path) and os.path.getsize(path) > 20_000:
            t = read_text(d["doc_id"])
            if t:
                txcache[d["doc_id"]] = t

    pairs, keys, indexes = find_pairs(docs, txcache)
    print(f"{len(keys)} key document(s), {len(indexes)} index document(s), "
          f"{len(pairs)} matched pair(s)", file=sys.stderr)
    for t in sorted(set(indexes) - set(keys)):
        print(f"  index with no companion key, skipped: {t[:66]}", file=sys.stderr)

    all_rows, all_orgs, report = [], [], []
    for idoc, key_doc, title in pairs:
        rows, orgs, agree, unresolved, n_key = parse_pair(idoc, key_doc, title, txcache)
        tot = agree["yes"] + agree["no"]
        rate = agree["yes"] / tot if tot else 0.0
        all_rows += rows
        all_orgs += orgs
        report.append({
            "title": title, "index_doc_id": idoc["doc_id"],
            "key_doc_id": key_doc["doc_id"], "n_key_companies": n_key,
            "n_person_ties": len(rows), "n_corporate_ties": len(orgs),
            "n_glossed": tot, "gloss_agreement": round(rate, 4),
            "n_unresolved_refs": sum(unresolved.values()),
        })
        print(f"\n{title}", file=sys.stderr)
        print(f"  key companies      {n_key:,}", file=sys.stderr)
        print(f"  person ties        {len(rows):,}", file=sys.stderr)
        print(f"  corporate ties     {len(orgs):,}", file=sys.stderr)
        print(f"  gloss agreement    {100 * rate:.1f}%  ({tot:,} checkable)",
              file=sys.stderr)
        print(f"  unresolved refs    {sum(unresolved.values()):,}", file=sys.stderr)

    # Flag rows whose firm is already a node in the colonial dataset. The
    # annuaire covers the whole Paris Bourse, so most of it is metropolitan
    # and foreign business: merging it wholesale would change what this
    # dataset is. The flag lets a user take the colonial slice, or keep the
    # rest as the metropolitan context of colonial directors - which is
    # exactly what an interlocking-directorate study wants - without the
    # choice being made for them here.
    # Compare against firms with *dossier* evidence, not against companies.csv:
    # once build_network merges this stage, companies.csv contains these firms
    # by construction and the flag would read 100% for that reason alone.
    known = set()
    with open(os.path.join(PROC, "affiliations.csv"), encoding="utf-8", newline="") as fh:
        for a in csv.DictReader(fh):
            if a["company_key"]:
                known.add(a["company_key"])
    n_known = 0
    for r in all_rows + all_orgs:
        hit = r["company_key"] in known
        r["in_colonial_dataset"] = int(hit)
        n_known += hit
    print(f"  of which at a firm with dossier evidence too: {n_known:,} "
          f"({100 * n_known / max(1, len(all_rows) + len(all_orgs)):.0f}%)",
          file=sys.stderr)

    fields = ["doc_id", "company_key", "company_name", "person_key", "member_key",
              "name_clean", "surname", "given", "role", "year", "source_ref",
              "annotation", "region", "country", "sector", "anchor_type",
              "trigger", "parse_note", "member_raw", "entry_number",
              "source_genre", "in_colonial_dataset"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows + all_orgs)
    with open(REPORT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(report[0]) if report else ["title"])
        w.writeheader()
        w.writerows(report)

    people = len({r["person_key"] for r in all_rows})
    firms = len({r["company_key"] for r in all_rows + all_orgs})
    print(f"\nwrote {os.path.relpath(OUT, ROOT)}: {len(all_rows):,} person ties + "
          f"{len(all_orgs):,} corporate ties, {people:,} people, {firms:,} firms",
          file=sys.stderr)

    worst = min((r["gloss_agreement"] for r in report), default=1.0)
    if worst < args.min_agreement:
        raise SystemExit(
            f"gloss agreement {worst:.2f} below {args.min_agreement:.2f} - the "
            f"numbering may be misaligned; refusing to write a plausible-looking "
            f"but wrong dataset")


if __name__ == "__main__":
    main()
