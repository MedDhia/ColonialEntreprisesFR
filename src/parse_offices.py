"""Stage 3i - offices of state, and the colonial administration.

    python3 src/parse_offices.py             # -> person_offices.csv
    python3 src/parse_offices.py --audit 20  # print rows for hand-checking

Stage 3g reads the legislature. This one reads the executive, which in a
colonial dataset is the larger half: the corpus names a *gouverneur général*
15,595 times across 1,653 documents, a *résident supérieur* 5,770 times, a
*ministre des Colonies* 3,088 times. A company whose board holds a retired
governor-general of French West Africa is connected to the colonial state in a
way no parliamentary mandate captures, because the governor-general *was* the
state in the territory the company operated in - he signed its concessions,
set its labour regime and allocated its land.

The subject-resolution machinery is stage 3g's, imported rather than copied:
"whose title is this" has the same four registers - apposition, the compiler's
bracket, title-first, and the footnote career line - whether the title is
`député` or `gouverneur général`. Same kinship discipline, same disclaimers.

**What is new here is the reference trap, and it is much worse than for a
mandate.** A chamber is almost only ever mentioned as an attribute of a man. An
office is mentioned overwhelmingly as an *institution*:

    autorisée par arrêté du gouverneur général du 14 mars 1923
    concession accordée par le ministre des Colonies
    Le Gouverneur général de l'Algérie à monsieur Treille, député, Paris

None of those attributes the office to anyone, and all three are the normal way
the corpus mentions it. The defence is that a row is only emitted when
`subject_of` finds a named subject in one of the four registers, which requires
either a name-and-comma immediately before the title, a bracket, or a
recognised forename immediately after it. A bare `par le gouverneur général` has
none, so it yields nothing. `OFFICE_RE` matches **46,344** times across the
corpus and this stage emits **5,653 rows** — 12.2%. The other seven-eighths name
an office without naming its holder, and that ratio is the measurement: it is
what an office-mention corpus looks like once you refuse to guess who held it.

Four collisions needed their own rules, because the same word is two offices:

- **`administrateur`** alone is a company director, which is the entire rest of
  this dataset. Only `administrateur des colonies` and `administrateur des
  services civils` are the colonial civil-service rank, so the qualifier is
  required and `administrateur délégué` is never matched.
- **`gouverneur`** governs the Banque de France as well as Madagascar. A
  governorship over a bank is a state appointment but not a colonial one, so it
  is coded `state_bank`, not `colonial_governor`.
- **`préfet apostolique`** is a bishop.
- **Military rank** - `général`, `colonel`, `capitaine` - is not an office of
  state and is not read at all. In this corpus those words are honorifics
  attached to hundreds of directors and would swamp every other class.

**`former` is the column that matters most.** A *sitting* governor-general on a
board and a *retired* one are different objects: the first is a conflict of
interest, the second is a revolving door. `ancien gouverneur général`,
`ex-ministre` and `gouverneur honoraire` are all recorded as `former = 1`, and
`code_political_connections.py` keeps the two apart rather than summing them.

This stage adds nothing to the affiliation network. It writes one file, one row
per mention, and `code_political_connections.py` aggregates it.
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
import parse_mandates as M  # noqa: E402
from common import ensure_dir  # noqa: E402
from names import parse_person_name  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(PROC, "person_offices.csv")

# `former` markers, shared by every class. "honoraire" belongs here: an
# honorary governor is a retired one the state let keep the title.
_FORMER = (r"(?P<former>\b(?:anc(?:ien|\.)|ex|ci-devant)\s*-?\s*|"
           r"\b(?:pr[eé]c[eé]dent|sortant)\s+)?")

# What may follow the first word of a ministerial portfolio: another
# capitalised word (Travaux **Transports**), or one of the lower-case
# adjectives portfolios actually use.
_PORTFOLIO_MORE = (
    r"\s+(?:et\s+(?:des?\s+|du\s+|de\s+la\s+|de\s+l['’])?)?"
    r"[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]*"
    r"|\s+(?:publics?|publiques?|nationale?s?|[eé]trang[eè]res|sociales?|"
    r"civils?|militaires?|coloniales?|marchande|a[eé]rienne)")

# Ordered most specific first: the first class that matches at a position wins,
# so `gouverneur general` never falls through to `gouverneur`.
OFFICE_CLASSES = [
    ("head_of_state", r"pr[eé]sident\s+de\s+la\s+R[eé]publique"),
    ("colonial_governor",
     r"gouverneur\s+g[eé]n[eé]ral"
     r"|lieutenant[- ]gouverneur"
     r"|r[eé]sident\s+(?:g[eé]n[eé]ral|sup[eé]rieur)"
     r"|haut[- ]commissaire"
     r"|commissaire\s+de\s+la\s+R[eé]publique"
     # A bare "gouverneur de <colony>" is the office; a bare "gouverneur de la
     # Banque" is not, and is caught by `state_bank` below it only because the
     # territory list here does not admit it.
     r"|gouverneur\s+(?:de\s+la|de\s+l['’]|du|des|de)\s+(?:"
     r"Madagascar|Indochine|Cochinchine|Alg[eé]rie|Tunisie|Maroc|"
     r"S[eé]n[eé]gal|Soudan|Guin[eé]e|C[oô]te\s+d['’]Ivoire|Dahomey|Niger|"
     r"Mauritanie|Tchad|Gabon|Congo|Oubangui|Cameroun|Togo|"
     r"Nouvelle[- ]Cal[eé]donie|[EÉ]tablissements|Guyane|Martinique|"
     r"Guadeloupe|R[eé]union|C[oô]te\s+fran[cç]aise)"),
    ("state_bank",
     r"(?:sous-)?gouverneur\s+de\s+la\s+Banque\s+de\s+France"
     r"|gouverneur\s+du\s+Cr[eé]dit\s+[Ff]oncier"),
    # The portfolio has to be swallowed whole. Matching only `ministre des T`
    # left "ravaux publics et des" in the jurisdiction slot. The continuation
    # is a capitalised word or one of the handful of lower-case portfolio
    # adjectives, never an arbitrary word, or "ministre des Colonies a
    # déclaré que" swallows the sentence.
    ("minister",
     r"(?:sous-secr[eé]taire\s+d['’][EÉe]tat|ministre)"
     # `ministre de France à Tanger` and `ministre plénipotentiaire` are
     # diplomatic posts, not cabinet seats; they belong to `senior_state`.
     r"(?!\s+(?:de\s+France|pl[eé]nipotentiaire|[àa]\s))"
     r"\s+(?:d['’][EÉe]tat|(?:des?|du|de\s+la|de\s+l['’]|aux?|[àa]\s+l['’]|[àa])"
     r"\s*[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]*"
     rf"(?:{_PORTFOLIO_MORE}){{0,4}})"
     r"|ministre\s+d['’][EÉe]tat"
     r"|garde\s+des\s+[Ss]ceaux"),
    ("colonial_admin",
     r"administrateur\s+(?:en\s+chef\s+)?des\s+(?:colonies|services\s+civils)"
     r"|inspecteur\s+(?:g[eé]n[eé]ral\s+)?des\s+colonies"
     r"|secr[eé]taire\s+g[eé]n[eé]ral\s+du\s+gouvernement"
     r"|directeur\s+des\s+affaires\s+(?:[eé]conomiques|politiques|"
     r"indig[eè]nes)"),
    ("colonial_council",
     r"(?:d[eé]l[eé]gu[eé]|membre|vice-pr[eé]sident|pr[eé]sident)\s+"
     r"(?:du\s+)?[Cc]onseil\s+sup[eé]rieur\s+"
     r"(?:des\s+[Cc]olonies|de\s+la\s+France\s+d['’][Oo]utre-[Mm]er)"),
    ("senior_state",
     r"conseiller\s+d['’][EÉe]tat"
     r"|(?:sous-)?pr[eé]fet(?!\s+apostolique)(?:\s+de\s+police)?"
     r"|ministre\s+(?:de\s+France|pl[eé]nipotentiaire)"
     r"|ambassadeur\s+(?:de\s+France|[àa])"
     r"|ministre\s+pl[eé]nipotentiaire"
     r"|consul\s+g[eé]n[eé]ral"
     r"|tr[eé]sorier[- ]payeur\s+g[eé]n[eé]ral"
     r"|directeur\s+(?:g[eé]n[eé]ral\s+)?au\s+minist[eè]re"),
    ("local_elected", r"conseiller\s+g[eé]n[eé]ral|maire\s+(?:de|d['’])"),
]

OFFICE_RE = re.compile(
    r"(?i)" + _FORMER + r"\b(?P<office>"
    + "|".join(f"(?:{pat})" for _, pat in OFFICE_CLASSES) + r")")

# Which class an office string belongs to. Recomputed per match rather than
# captured by group, because one alternation per class would need nine named
# groups and the ordering guarantee is easier to read as a loop.
_CLASS_RE = [(name, re.compile(r"(?i)^\s*(?:" + pat + r")"))
             for name, pat in OFFICE_CLASSES]

# The territory or department the office was held over: "gouverneur general de
# l'Afrique occidentale francaise", "prefet du Nord", "ministre des Colonies".
# No `(?i)` flag, deliberately: it applies to the whole pattern, so it would
# make every `[A-Z]` class match lower case too, and "haut-commissaire de la
# République française par intérim" then yielded the jurisdiction "République
# française par". The prefix words are spelled lower case because that is how
# they occur.
JURISDICTION_RE = re.compile(
    r"^[ \xa0]*(?:de\s+la\s+|de\s+l['’]|du\s+|des\s+|de\s+|d['’]|au\s+|"
    r"en\s+)?(?P<place>[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]*"
    r"(?:[ \xa0](?:de|du|des|d[’']|et)?[ \xa0]?"
    r"[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]*){0,2})")

# A jurisdiction slot filled by something that is not a place.
NOT_A_JURISDICTION_RE = re.compile(
    r"(?i)^(?:M|MM|Mme|Monsieur|Messieurs|le|la|les|ce|cette|"
    r"[EÉ]tat|R[eé]publique|France|Conseil|Chambre|S[eé]nat|Gouvernement|"
    r"Administration|Commission|Direction|Service|Cabinet|Comit[eé])$")

# `former` is also written *after* the office: "gouverneur général honoraire
# des colonies", "administrateur en chef des colonies, en retraite". An honorary
# governor is a retired one the state let keep the title.
FORMER_AFTER_RE = re.compile(
    r"(?i)^[ \xa0,]*(?:honoraire|en\s+retraite|retrait[eé]|"
    r"d[eé]missionnaire|sortant)\b")

# A foreign government's office. The men are real and sometimes sat on these
# boards, but "ministre du Shipping" is a British cabinet seat and coding it
# beside a French one would make the column mean two things.
# Not anchored to the end of the window: the honorific sits before the *name*
# ("avec sir Joseph Maclay, ministre du Shipping"), so anchoring it where the
# office starts meant it never matched.
FOREIGN_HONORIFIC_RE = re.compile(
    r"(?i)\b(?:sir|lord|lady|herr|signor|se[nñ]or|mister|mr|mrs|"
    r"his\s+excellency|right\s+hon)\b\.?\s+[A-Z]")

TAIL = 72               # how far past the office a jurisdiction may sit
BACK = 220              # how far back the subject may sit


def office_class(office: str) -> str:
    for name, rx in _CLASS_RE:
        if rx.match(office):
            return name
    return "other"


def jurisdiction(tail: str) -> str:
    """The territory an office was held over, or "" when not stated."""
    m = JURISDICTION_RE.match(M.flatten(tail))
    if not m:
        return ""
    place = m.group("place").strip(" ,.;")
    # Tested on the first word, not the whole run: "Gouvernement Général" is
    # not a place, and an exact-match test on the pair let it through.
    if not place or NOT_A_JURISDICTION_RE.match(place.split()[0]):
        return ""
    return M.normalise_seat(place)


def mentions(text: str):
    """Yield `(pattern, subject, office_class, office_raw, place, former, ev)`
    for every office the document attributes to a named person."""
    flat = text.replace("\xa0", " ")
    heads = M._entry_heads(flat)
    for m in OFFICE_RE.finditer(flat):
        back = flat[max(0, m.start() - BACK):m.start()]
        if M.kinship_before(back):
            continue
        tail = flat[m.end():m.end() + TAIL]
        pattern, subject, _ = M.subject_of(flat, back, tail, m.start(), heads)
        if not subject:
            continue
        if FOREIGN_HONORIFIC_RE.search(M.flatten(back)[-44:]):
            continue
        office_raw = M.flatten(m.group("office")).strip()
        former = bool(m.group("former")) or bool(FORMER_AFTER_RE.match(tail))
        yield (pattern, subject, office_class(office_raw), office_raw,
               jurisdiction(tail), former,
               M.flatten(flat[max(0, m.start() - 80):m.end() + 80]))


def load(name):
    with open(os.path.join(PROC, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=0,
                    help="print this many random rows for hand-checking")
    ap.add_argument("--limit", type=int, default=0, help="first N documents")
    args = ap.parse_args()

    docs = load("documents.csv")
    if args.limit:
        docs = docs[:args.limit]
    keys = M.network_keys()

    rows, classes, pats, seen = [], collections.Counter(), collections.Counter(), set()
    for doc in docs:
        text = B.read_text(doc["doc_id"])
        if not text or not OFFICE_RE.search(text):
            continue
        for pat, subject, klass, raw, place, former, ev in mentions(text):
            parsed = parse_person_name(subject)
            if not parsed["person_key"] or not parsed["surname"]:
                continue
            resolved = keys.get(parsed["person_key"], "")
            sig = (doc["doc_id"], resolved or parsed["person_key"], klass,
                   place, former)
            if sig in seen:
                continue
            seen.add(sig)
            classes[klass] += 1
            pats[pat] += 1
            rows.append({
                "doc_id": doc["doc_id"],
                "person_key": parsed["person_key"],
                "person_id": resolved,
                "in_network": "1" if resolved else "0",
                "name_clean": parsed["name_clean"],
                "surname": parsed["surname"],
                "given": parsed["given"],
                "office_class": klass,
                "office_raw": raw[:60],
                "jurisdiction": place,
                "former": "1" if former else "0",
                "pattern": pat,
                "evidence": ev[:200],
                "source_ref": doc["name_normalised"] or doc["name_listed"],
                "region": doc.get("region", ""),
                "country": doc.get("country", ""),
            })

    ensure_dir(PROC)
    fields = list(rows[0].keys()) if rows else ["doc_id"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    inn = [r for r in rows if r["in_network"] == "1"]
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(rows):,} mentions, "
          f"{len({r['person_key'] for r in rows}):,} people, "
          f"{len({r['doc_id'] for r in rows}):,} documents", file=sys.stderr)
    print(f"  in the network: {len(inn):,} mentions, "
          f"{len({r['person_id'] for r in inn}):,} people", file=sys.stderr)
    print(f"  by class: {classes.most_common()}", file=sys.stderr)
    print(f"  by register: {pats.most_common()}", file=sys.stderr)
    print(f"  former office-holders: "
          f"{sum(1 for r in rows if r['former'] == '1'):,}; with a "
          f"jurisdiction: {sum(1 for r in rows if r['jurisdiction']):,}",
          file=sys.stderr)

    if args.audit and rows:
        rng = random.Random(5)
        for r in rng.sample(rows, min(args.audit, len(rows))):
            print(f"\n{r['name_clean']} = {r['office_class']}"
                  f" ({r['office_raw']}) / {r['jurisdiction'] or '-'}"
                  f"  [former={r['former']}, {r['pattern']},"
                  f" in_network={r['in_network']}]"
                  f"\n   {r['evidence']}")


if __name__ == "__main__":
    main()
