"""Stage 3d - resolve the compiler's abbreviated affiliation notes.

    python3 src/resolve_annotations.py   # -> data/processed/affiliations_annotations.csv

Board lists carry the compiler's own identification of a director's *other*
seats, written as abbreviations beside the name:

    A. R. Fontaine (Distill. Indoch.)   MM. Dupont (Cie gén. transatl.)

That is interlock evidence stated by the source itself. `build_network.py`
already emits 20,208 of these as candidates, but only 2,523 resolve: exact
name matches and catalogue acronyms. The remaining 17,685 fail because the
note is abbreviated and the company name is not - "Cotonn. St-Quentin" is
*Cotonnière de Saint-Quentin*, "Fin. fr.-marocaine" is *Financière
franco-marocaine*.

## Matching by token prefix, in order

Each note and each company name is reduced to content tokens. A note matches a
name when **every** note token is a prefix of a name token and the tokens
appear in the same order. "cotonn st quentin" matches "cotonniere de saint
quentin" because *cotonn* prefixes *cotonniere*, *st* expands to *saint*, and
*quentin* matches exactly. Prefix matching needs no list of abbreviations,
which matters because the compiler invents them freely; a short alias table
handles only the forms that are not prefixes of what they stand for (*Cie* for
*Compagnie*, *Bq* for *Banque*, *St* for *Saint*).

## Why ambiguity is dropped rather than guessed

A note that matches several firms is discarded, not resolved to the most
likely. "Mines" prefixes eighty company names, and picking one would
manufacture a specific, checkable, wrong claim. The same logic rejects notes
whose content reduces to a single short token: the note has to carry enough
signal to identify one firm.

These ties are written to their own file with `source_genre = "annotation"`
and are **not** merged by default. They are the compiler's assertion, not a
transcribed board list, and they carry no year of their own beyond the
observation they sit in.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import PLACES  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(PROC, "affiliations_annotations.csv")

# Forms that are not prefixes of the word they abbreviate.
ALIASES = {
    "cie": "compagnie", "cies": "compagnies", "sté": "societe", "ste": "societe",
    "sté.": "societe", "soc": "societe", "sce": "societe", "bq": "banque",
    "bque": "banque", "st": "saint", "ste-": "sainte", "sts": "saints",
    "éts": "etablissements", "ets": "etablissements", "étab": "etablissements",
    "cred": "credit", "cred.": "credit", "cred": "credit",
    "gle": "generale", "gles": "generales", "gal": "general",
    "nlle": "nouvelle", "nle": "nouvelle", "fse": "francaise", "fsc": "francaise",
    "cial": "commercial", "ciale": "commerciale", "cciale": "commerciale",
    "cptoir": "comptoir", "cpt": "comptoir", "mines": "mines",
    "chns": "chemins", "ch": "chemins", "fer": "fer",
    "elect": "electrique", "élect": "electrique",
}

# Tokens that carry no identifying signal.
STOP = {
    "de", "du", "des", "d", "la", "le", "les", "l", "et", "en", "a", "au", "aux",
    "pour", "sur", "the", "of", "and", "societe", "compagnie", "cie", "anonyme",
    "generale", "nouvelle", "francaise", "francais", "sa", "sarl",
}

MIN_TOKEN = 2
MIN_DISTINCTIVE = 6   # a single token must be at least this long to stand alone

# A company node whose name is really a biographical fragment. These exist in
# companies.csv - the parsers occasionally promote a prose span - and matching
# against them turns one bad node into many bad ties. Rejected as targets here;
# the nodes themselves are a separate problem.
# NOT re.I, and no character classes that depend on case: under IGNORECASE
# "^[a-z]" matches an uppercase initial too, so the first version of this
# pattern rejected every company name in the file - "Banque de l'Indochine"
# included. The same trap is documented for ORG_ARTICLE_RE in names.py.
JUNK_NAME_RE = re.compile(
    r"\b\d{4}-\d{2}\b"                       # "1921-22" - a career date range
    r"|\bmin\.\s+(?:Int|Instruc|Fin|Guerre)"  # ministerial posts
    r"|\bpolytechnic"
    r"|\bv\.-pdt\b"
    r"|\bn[ée]\s+en\s+\d{4}"
    r"|\bfils\s+de\b")


PLACE_FOLD: set[str] = set()


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def tokens(text: str) -> list[str]:
    out = []
    for raw in re.split(r"[^0-9A-Za-zÀ-ÿ]+", fold(text)):
        if not raw:
            continue
        t = ALIASES.get(raw, raw)
        if len(t) >= MIN_TOKEN:
            out.append(t)
    return out


# An abbreviation of a stopword is still a stopword. "gén." is not in STOP but
# "générale" is, so a note reduced to ["gen", "transatl"] could never match a
# name reduced to ["transatlantique"]: the note kept a token the name had
# dropped. Prefixes are capped at four characters so that a real word is not
# discarded for merely starting like a stopword.
STOP_PREFIXES = {w[:n] for w in STOP for n in range(2, 5) if len(w) > n}


def content(toks: list[str]) -> list[str]:
    return [t for t in toks if t not in STOP and t not in STOP_PREFIXES]


def matches(note: list[str], name: list[str]) -> bool:
    """Every note token prefixes a name token, in order."""
    i = 0
    for nt in note:
        while i < len(name) and not name[i].startswith(nt):
            i += 1
        if i == len(name):
            return False
        i += 1
    return True


def build_index(companies: list[dict]) -> list[tuple[str, str, list[str]]]:
    idx = []
    for c in companies:
        name = c.get("name") or ""
        if not name or len(name) > 90 or JUNK_NAME_RE.search(name):
            continue
        idx.append((c["company_id"], name, tokens(name)))
    return idx


def resolve(note: str, index, by_first: dict[str, list[int]]) -> tuple[str, str, str]:
    """Return (company_id, company_name, method) or ('', '', reason)."""
    # A territory is not a firm. "Afrique Équatoriale Française" matched
    # "Société Générale Française de l'Afrique équatoriale" on prefixes, which
    # asserts a directorship from a place name.
    if fold(re.sub(r"[^0-9A-Za-zÀ-ÿ\s'’-]", " ", note)).strip() in PLACE_FOLD:
        return "", "", "place_name"

    nt = content(tokens(note))
    if not nt:
        return "", "", "no_content_tokens"
    # A single token is not enough to identify a firm by prefix: "Armand"
    # prefixes "Armandon & Cie", "Zafiropulo" prefixed an unrelated agency.
    # One token resolves only on an exact whole-name match.
    if len(nt) == 1:
        exact = [(cid, name) for cid, name, toks in index
                 if content(toks) == nt]
        if len({cid for cid, _ in exact}) == 1:
            return exact[0][0], exact[0][1], "exact_single_token"
        return "", "", "single_token"

    # Candidates are restricted to names containing a token starting with the
    # note's first content token; scanning 10,000 names per note is the naive
    # version and is ~200x slower for the same answer.
    hits = []
    for i in by_first.get(nt[0][:MIN_TOKEN], ()):
        cid, name, name_toks = index[i]
        if matches(nt, content(name_toks)) or matches(nt, name_toks):
            hits.append((cid, name))
    if not hits:
        return "", "", "no_match"
    uniq = {cid for cid, _ in hits}
    if len(uniq) > 1:
        # Prefer an exact token-count match if it is unique - "Banque de
        # l'Indochine" should not be ambiguous merely because longer names
        # also start that way.
        exact = [(cid, name) for cid, name in hits
                 if len(content(tokens(name))) == len(nt)]
        if len({cid for cid, _ in exact}) == 1:
            return exact[0][0], exact[0][1], "prefix_exact_length"
        return "", "", f"ambiguous_{len(uniq)}"
    return hits[0][0], hits[0][1], "prefix"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=0)
    args = ap.parse_args()

    def load(name):
        with open(os.path.join(PROC, name), encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    PLACE_FOLD.update(fold(p) for p in PLACES)
    # Territory names the catalogue uses that are not in places.txt.
    PLACE_FOLD.update({
        "afrique equatoriale francaise", "afrique occidentale francaise",
        "afrique du nord", "afrique noire", "indochine", "cochinchine",
        "tonkin", "annam", "cambodge", "laos", "maroc", "algerie", "tunisie",
        "madagascar", "senegal", "soudan", "guinee", "cote d ivoire", "dahomey",
        "gabon", "congo", "cameroun", "tchad", "oubangui chari", "syrie liban",
        "nouvelle caledonie", "tahiti", "reunion", "guadeloupe", "martinique",
        "guyane", "djibouti", "france", "paris", "empire", "colonies",
    })
    companies = load("companies.csv")
    cands = load("candidate_ties_from_annotations.csv")
    index = build_index(companies)
    by_first: dict[str, list[int]] = defaultdict(list)
    for i, (_, _, toks) in enumerate(index):
        for t in set(content(toks) or toks):
            by_first[t[:MIN_TOKEN]].append(i)

    rows, reasons, audit = [], Counter(), []
    for c in cands:
        note = c["annotation_raw"]
        # The place guard applies to upstream matches too: they were resolved
        # before this check existed, so "Afrique Équatoriale Française" came
        # through as a firm.
        if fold(re.sub(r"[^0-9A-Za-zÀ-ÿ\s'’-]", " ", note)).strip() in PLACE_FOLD:
            reasons["place_name"] += 1
            continue
        cid, cname, method = c["candidate_company_id"], c["candidate_company_name"], ""
        if cid and JUNK_NAME_RE.search(cname or ""):
            reasons["junk_target"] += 1
            continue
        if cid:
            method = c["match_method"]          # already resolved upstream
        else:
            cid, cname, method = resolve(note, index, by_first)
        if not cid:
            reasons[method] += 1
            continue
        if cid == c["from_company_id"]:
            reasons["self_reference"] += 1       # the note names the firm itself
            continue
        reasons[method] += 1
        rows.append({
            "person_id": c["person_id"],
            "company_key": cid,
            "company_name": cname,
            "role": "administrateur",
            "year": c["year"],
            "source_ref": c["source_ref"],
            "doc_id": c["doc_id"],
            "annotation": c["annotation_raw"],
            "from_company_id": c["from_company_id"],
            "match_method": method,
            "n_observations": c["n_observations"],
            "source_genre": "annotation",
        })
        audit.append((c["annotation_raw"], cname, method))

    if args.audit:
        random.seed(7)
        for a, n, m in random.sample(audit, min(args.audit, len(audit))):
            print(f"{a[:38]:<38} -> {n[:52]:<52} [{m}]")
        return

    fields = ["person_id", "company_key", "company_name", "role", "year",
              "source_ref", "doc_id", "annotation", "from_company_id",
              "match_method", "n_observations", "source_genre"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    pairs = {(r["person_id"], r["company_key"]) for r in rows}
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(rows):,} ties, "
          f"{len(pairs):,} person-firm pairs, "
          f"{len({r['company_key'] for r in rows}):,} firms", file=sys.stderr)
    print(f"  resolved {len(rows):,} of {len(cands):,} candidates "
          f"({100 * len(rows) / len(cands):.0f}%)", file=sys.stderr)
    print("  by method/reason:", dict(reasons.most_common(9)), file=sys.stderr)


if __name__ == "__main__":
    main()
