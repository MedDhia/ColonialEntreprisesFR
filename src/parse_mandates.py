"""Stage 3g - parliamentary mandates.

    python3 src/parse_mandates.py             # -> person_mandates.csv
    python3 src/parse_mandates.py --audit 20  # print rows for hand-checking

The corpus names deputies and senators 9,692 times across 1,415 documents, and
not one of those mentions is a tie, so none of the six affiliation parsers
records any of them. They are worth recording separately, because a
directorship held by a sitting parliamentarian is a different object from a
directorship held by an engineer: it is the point where the colonial firm
touches the legislature that votes its concessions, its tariffs and its
budgets.

This stage reads the mandate, not the directorship. It answers "was this man in
the Chamber or the Senate, for where, and when" and leaves the affiliation
network exactly as it was. `make_legislative_layer.py` then joins the two.

Four registers carry a mandate, and they differ in where the *subject* sits
relative to the title:

1. **Apposition** - the subject is named, then the title follows a comma.

       M. Ernest Outrey, député de la Cochinchine
       ACCAMBRAY (Léon), député [1914-1932] et CG Aisne
       M. Raoul Péret, sénateur, ancien ministre

2. **Compiler bracket** - the subject is a board member and the title sits in
   the square-bracket note the compiler appends to the name.

       Camille Krantz* [député d'Épinal 1891-1910, CNEP]
       Justin Perchot* [Commentry-Oissel, député puis sénateur des Basses-Alpes]

3. **Title first** - the title governs the name.

       le sénateur Ernest Feray
       du député Samuel de Lestapis

4. **Footnote career line** - the subject is the footnote's own header and the
   mandate is one clause of the career prose that follows it.

       Jules Bozerian (Paris, 1825-Paris, 1893) : avocat, député (1871-1876),
       puis senateur (1876-1893) du Loir-et-Cher

**The kinship trap, which is the whole precision problem here.** The compiler
is a genealogist as much as a company historian, and the mandate he mentions
next to a name is very often *not that man's*:

    Maurice Piot [fils de Leon Piot (1845-1922), depute de l'Aude 1876-1877]
    Ch. Riotteau [fils du senateur-maire de Granville Emile Riotteau]
    Marie a Geneviève Merillon, fille d'un depute de la Gironde

Reading these as mandates would put three men in a Chamber none of them ever
sat in. Every register is therefore filtered by `kinship_before()`, which looks
at the *clause* the title sits in - back to the nearest `.`, `;` or bracket
edge, not the whole note - and rejects the mandate if a kinship word governs
it. Scoping to the clause is what lets `[ep. Potin. Anc. depute de la Nievre]`
through: Heuzey married a Potin *and* sat for the Nièvre, and the full stop
says so.

**What this stage does not claim.** A mandate mention is evidence that the
corpus describes someone as a deputy or senator; it is not a parliamentary
roster, and a man who sat for twenty years may appear once or forty times. The
mention file is therefore the raw output, one row per mention, and every
consumer aggregates it. Nothing here is checked against the Assemblée
nationale's own biographical dictionary - the constituency and the years are
the compiler's, with his errors intact.
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
from common import FORENAMES, ensure_dir, strip_accents  # noqa: E402
from names import parse_person_name  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(PROC, "person_mandates.csv")

YEAR = r"1[6-9]\d\d|20\d\d"

# Name particles, and a name token that tolerates the two things the compiler
# does to forenames: abbreviates them ("Ch. Heuzey") and restores them in
# square brackets in place ("M[aurice] Piot", "A[rthur] Espivent").
_PARTICLE = r"(?:de|du|des|d[’']|le|la|les|van|von|di|del|della|el|ben|bel|ould)"
# The trailing full stop is allowed only on a short token - an initial or the
# compiler's "Ch.", "Th.", "Aug.". Allowing it on any token made a sentence end
# part of the next name: "26, rue d'Athenes. Ferdinand Buisson, ancien depute"
# was read as a man called Athènes Ferdinand Buisson.
_TOKEN = (r"[A-ZÉÈÀÂÎÔÛÇ](?:[A-Za-zÀ-ÿ’'\-]{0,2}\.|[A-Za-zÀ-ÿ’'\-]*)"
          r"(?:\[[A-Za-zÀ-ÿ’'\-]{2,18}\])?")
_NAME = (rf"(?:\[[A-Za-zÀ-ÿ’'\- ]{{2,20}}\]\s*)?"
         rf"{_TOKEN}(?:[ \xa0](?:{_PARTICLE}[ \xa0])?{_TOKEN}){{0,3}}")

# The two chambers. `ministre` is deliberately *not* a chamber - it is an
# executive office and it appears far more often as a reference to whoever
# happened to hold it ("charge de mission par le ministre des colonies") than
# as an attribute of a named man. It is recorded as a flag on the mention
# instead, read from the same evidence window, where it is the subject's own.
CHAMBER_RE = re.compile(
    r"(?i)(?P<former>\b(?:anc(?:ien|\.)|ex)\s*-?\s*)?"
    r"\b(?P<chamber>d[eé]put[eé]|s[eé]nateur|s[eé]natrice)"
    r"(?:\s*[-–]\s*maire)?\b")

CHAMBERS = {"depute": "Chamber of Deputies", "senateur": "Senate",
            "senatrice": "Senate"}

MINISTER_RE = re.compile(
    r"(?i)\b(?:anc(?:ien|\.)\s*)?ministre\b|\bsous-secr[eé]taire\s+d['’][EÉe]tat\b")

# `depute` also means "delegate", and the compiler tracks freemasonry: "G. L.
# (depute), depute au convent 1930-1931 de la Loge L'Etoile flamboyante" is a
# lodge delegate, not a member of the Chamber.
DELEGATE_RE = re.compile(
    r"(?i)^\s*(?:au|aux|du|de\s+la)?\s*(?:convent|loge|chapitre|"
    r"conseil\s+de\s+l['’]ordre|grand\s+orient|ob[eé]dience|"
    r"congr[eè]s|assembl[eé]e\s+consulaire|syndicat|f[eé]d[eé]ration)\b")

# The compiler's own warning that the man beside the mandate is *not* the
# director: "R. Carcassonne : probablement a distinguer de l'avocat Roger
# Carcassonne, senateur socialiste (1946-1971)". Reading that as a mandate
# asserts exactly what the source denies.
DISCLAIMER_RE = re.compile(
    r"(?i)\b(?:[àa]\s+distinguer\s+de|ne\s+pas\s+confondre|homonyme|"
    r"sans\s+lien|rien\s+[àa]\s+voir|probablement\s+[àa]|s['’]agit-il)\b")

# A four-digit year in the corpus is very often a newspaper date, and the
# citation sits within a few words of the title: "par Henri COSNIER, depute de
# l'Indre (Les Annales coloniales, 2 janvier 1913)". A month name before the
# year, or a periodical's parenthesis opening between the title and the year,
# means the year dates the clipping and not the mandate.
MONTH_RE = re.compile(
    r"(?i)\b(?:janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
    r"septembre|octobre|novembre|d[eé]cembre)\b\s*$")
CITATION_OPEN_RE = re.compile(r"\((?:Le |La |Les |L['’]|Bulletin|Annales|"
                              r"Journal|Revue|Cote |BALO|Écho|Echo)")

# Kinship words that steal a mandate from the man being named. `ep.`/`epouse`
# is here because "X [ep. fille de Y, depute]" is Y's mandate, not X's; the
# clause scoping in `kinship_before` is what keeps it from also rejecting
# "X [ep. Potin. Anc. depute de la Nievre]".
KINSHIP_RE = re.compile(
    r"(?i)\b(?:fils|fille|f[rè]ere|fr[eè]re|s[oœ]ur|soeur|neveu|ni[eè]ce|"
    r"cousin[e]?|gendre|beau-(?:p[eè]re|fr[eè]re|fils)|belle-(?:m[eè]re|fille)|"
    r"petit[- ]fils|petite[- ]fille|arri[eè]re-petit|veuve|veuf|"
    r"parent[eé]|apparent[eé]|descendant|a[iï]eul|grand-p[eè]re|oncle|"
    r"[eé]p(?:\.|ouse|ous[eé]e?)|mari[eé]e?\s+[aà]|union\s+avec|"
    r"famille\s+de|p[eè]re)\b")

# Where a clause starts, looking backwards: a sentence end, a semicolon, or a
# bracket edge. Abbreviations end in a full stop too ("Anc.", "dir."), and that
# is a feature - it is exactly the boundary that separates the compiler's
# stacked clauses.
CLAUSE_EDGE_RE = re.compile(r"[.;\[\]]")

# Constituency: "de la Cochinchine", "d'Epinal", "du Morbihan", "des
# Basses-Alpes", or bare after the title ("depute Hte-Saone"). Anchored, not
# searched: the phrase has to follow the title directly, because the slot after
# the next comma is another office entirely - "depute, vice-president de la
# Commission des Colonies" is not a deputy for the Commission des Colonies.
_SEAT_TOKEN = r"[A-ZÉÈÀÂÎÔÛÇ](?:[A-Za-zÀ-ÿ’'\-]|\.(?=[-A-ZÉÈÀÂÎÔÛÇ]))*"
# The connector between seat words is required, not optional. Without it two
# capitalised words in a row ran together across a heading: "senateur du Nord"
# followed by the article title "L'Afrique Equatoriale Francaise" became one
# constituency. Real multi-word seats carry the connector - "Territoire de
# Belfort", "Loir et Cher" - or are hyphenated into a single token.
_PLACE = (rf"{_SEAT_TOKEN}(?:[ \xa0](?:de|du|des|d[’']|et)[ \xa0]?"
          rf"{_SEAT_TOKEN}){{0,2}}")

# The compiler abbreviates departments the way the almanacs do. Expanding them
# is what lets "Hte-Saone", "Hte- Saone" and "Haute-Saone" count as one seat.
SEAT_ABBREV = {
    "b.-du-rh": "Bouches-du-Rhône", "b-du-rh": "Bouches-du-Rhône",
    "hte": "Haute", "htes": "Hautes", "bse": "Basse", "bses": "Basses",
    "bas": "Bas", "s.-et-o": "Seine-et-Oise", "s.-et-m": "Seine-et-Marne",
    "s.-inf": "Seine-Inférieure", "sne": "Seine", "l.-et-g": "Lot-et-Garonne",
    "p.-de-c": "Pas-de-Calais", "m.-et-l": "Maine-et-Loire",
    "m.-et-m": "Meurthe-et-Moselle", "i.-et-l": "Indre-et-Loire",
    "i.-et-v": "Ille-et-Vilaine", "ille-et-villaine": "Ille-et-Vilaine",
    "c.-du-n": "Côtes-du-Nord", "p.-o": "Pyrénées-Orientales",
    "a.-m": "Alpes-Maritimes", "l.-inf": "Loire-Inférieure",
    "rh": "Rhône", "gir": "Gironde", "cochinch": "Cochinchine",
}


def normalise_seat(place: str) -> str:
    """Expand the compiler's department shorthand; leave anything else alone."""
    place = re.sub(r"-\s+", "-", re.sub(r"\s+", " ", place)).strip(" ,.;-")
    if not place:
        return ""
    key = strip_accents(place).lower().rstrip(".")
    if key in SEAT_ABBREV:
        return SEAT_ABBREV[key]
    parts = re.split(r"(-)", place)
    out = []
    for p in parts:
        k = strip_accents(p).lower().rstrip(".")
        out.append(SEAT_ABBREV.get(k, p) if k not in ("", "-") else p)
    return "".join(out)
CONSTITUENCY_RE = re.compile(
    rf"^[ \xa0]*(?:de\s+la\s+|de\s+l[’']|du\s+|des\s+|de\s+|d[’'])?"
    rf"(?P<place>{_PLACE})")

# Heads that fill the constituency slot without being a constituency. The first
# three are the institution rather than the seat; the rest are foreign upper
# houses, which the corpus reports for Italian and Belgian directors.
NOT_A_SEAT_RE = re.compile(
    r"(?i)^(?:maire|ville|circonscription|s[eé]nat|parlement|chambre|"
    r"assembl[eé]e|commission|conseil|groupe|budget|"
    r"royaume|empire|italie|belgique|espagne|portugal|suisse|roumanie)$")

# Mandates in another country's legislature. They are real mandates and the men
# are real directors, but a seat in the Italian Senate is not a seat in the
# body that legislated for the French empire, so they are not French mandates
# and are dropped rather than mixed in.
FOREIGN_HOUSE_RE = re.compile(
    r"(?i)\b(?:du\s+Royaume|d[’']Italie|italien(?:ne)?s?|belge|"
    r"de\s+Belgique|espagnol|portugais|roumain|Reichstag|Cortes|"
    r"Westminster|britannique)\b")

YEAR_CLUSTER_RE = re.compile(
    rf"(?:{YEAR})(?:\s*[-–—]\s*(?:{YEAR})?)?"
    rf"(?:\s*,\s*(?:{YEAR})(?:\s*[-–—]\s*(?:{YEAR})?)?)*")

TAIL_CHARS = 96          # how far past the title a constituency/date may sit
BRACKET_CHARS = 260      # longest compiler bracket read as one note
ENTRY_CHARS = 700        # how far into a footnote a career clause may sit

# Honorifics that mark the token run before a comma as a person rather than a
# place or an occupation. "monsieur" lowercase is in the list because the
# compiler quotes letters ("a monsieur Treille, depute, Paris").
HONORIFIC_RE = re.compile(
    r"(?i)(?:MM?\.|Mme|Mlle|Me|Mgr|messieurs?|monsieur|madame|"
    r"le\s+(?:g[eé]n[eé]ral|colonel|commandant|capitaine|docteur|"
    r"pr[eé]sident|b[aâ]tonnier|marquis|comte|baron|vicomte))\s*$")

# Words that look like a name to the token pattern but never are, in the slot
# immediately before ", depute". Occupations are the common case: the compiler
# writes "avocat, depute" and "industriel, senateur" constantly, and those
# rows carry no subject at all.
NOT_A_SUBJECT_RE = re.compile(
    r"(?i)^(?:monsieur|madame|messieurs?|le|la|les|un|une|"
    r"conseiller|avocat|industriel|banquier|ing[eé]nieur|n[eé]gociant|"
    r"propri[eé]taire|colon|planteur|docteur|m[eé]decin|"
    r"pr[eé]sident|vice-pr[eé]sident|administrateur|directeur|g[eé]rant|"
    r"gouverneur|r[eé]sident|pr[eé]fet|maire|ministre|s[eé]nateur|d[eé]put[eé]|"
    r"paris|alger|oran|tunis|rabat|saigon|sa[iï]gon|hano[iï]|dakar)$")

# The footnote header: a mixed-case name, life dates, a colon. This is the only
# entry header this stage trusts. An earlier draft also segmented on the
# dictionary form (a capitalised surname at line start) and that pattern
# matches newspaper headlines - "NAVIRES ATTENDUS AUJOURD'HUI" - so a mandate
# named anywhere in the column below one was attributed to it.
FOOTNOTE_HEAD_RE = re.compile(
    r"(?m)^[ \t]*(?P<name>[A-ZÉÈÀÂÎÔÛÇ][^\n:()]{2,52}?)\s*"
    rf"\(\s*(?P<dates>[^)\n]{{0,30}}?\b(?:{YEAR})\b[^)\n]{{0,26}})\)\s*:")

# Headers with the footnote's shape that do not name a person: a decoration
# line, a narrative sentence opening with a preposition, an office.
HEAD_NOT_PERSON_RE = re.compile(
    r"(?i)^(?:(?:grand[- ])?(?:chevalier|officier|commandeur)|m[eé]daill|croix|"
    r"palmes|promotion|d[eé]cor|[àa]\s|au\s|aux\s|dans\s|en\s|d[eè]s\s|"
    r"apr[eè]s\s|avant\s|lors\s|conseiller|pr[eé]sident|directeur|"
    r"administrateur|ing[eé]nieur|inspecteur|gouverneur|r[eé]sident|"
    r"secr[eé]taire|l[eé]gion|annuaire|bulletin)")

# What ends a footnote before its character budget does: a blank line, or the
# compiler's rule of dashes between clippings.
ENTRY_BREAK_RE = re.compile(r"\n[ \t]*\n|[—–-]{4,}")


def flatten(window: str) -> str:
    """One line, single spaces. Applied per window, never to the document.

    The document keeps its line breaks because `FOOTNOTE_HEAD_RE` anchors on
    them and `ENTRY_BREAK_RE` needs the blank line between paragraphs. Only the
    short windows a mandate is read out of are flattened, which is also what
    lets a name or a department split across an OCR line break be read as one.
    """
    window = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", window)
    return re.sub(r"\s+", " ", window.replace("\xa0", " "))


def clause_before(window: str) -> str:
    """The text from the start of the current clause to the end of `window`."""
    edges = [m.end() for m in CLAUSE_EDGE_RE.finditer(window)]
    return window[edges[-1]:] if edges else window


def kinship_before(window: str) -> bool:
    """Whether a kinship word governs the title at the end of `window`."""
    clause = clause_before(flatten(window))
    return bool(KINSHIP_RE.search(clause) or DISCLAIMER_RE.search(clause))


def year_spans(raw: str) -> list[tuple[int, int]]:
    """Parse "1885-1889, 1893-1898" into [(1885, 1889), (1893, 1898)]."""
    out = []
    for part in re.split(r"\s*,\s*", raw):
        yrs = [int(y) for y in re.findall(YEAR, part)]
        if not yrs:
            continue
        out.append((yrs[0], yrs[-1] if len(yrs) > 1 else yrs[0]))
    return out


def _dates_a_mandate(win: str, m: re.Match) -> bool:
    """Whether a year run beside a title dates the mandate.

    Most four-digit years near a title date something else - the clipping it
    appears in, the budget under debate, the election the man lost:

        depute, sur le budget du ministere de la marine pour 1889
        CHAGNAUD Leon, senateur de la Creuse, non reelu en 1929
        par Henri COSNIER, depute de l'Indre (Les Annales coloniales, 1913)

    A mandate's dates, by contrast, are written the way a term of office is
    written: bracketed after the title, or as a span. A bare single year is
    ambiguous and is therefore not read, which loses "Elu depute de la Correze
    en 1893" and is the right trade.
    """
    before = win[:m.start()]
    if MONTH_RE.search(before) or CITATION_OPEN_RE.search(before):
        return False
    if re.search(r"[-–—]", m.group(0)):
        return True
    opens = before.count("(") + before.count("[")
    closes = before.count(")") + before.count("]")
    return opens > closes


def read_tail(tail: str) -> tuple[str, str, list[tuple[int, int]]]:
    """Constituency and dates from the text following a title.

    The two orders both occur - "depute de la Gironde 1919-1924" and "depute
    (1871-1876) ... du Loir-et-Cher" - so both are read from one window, which
    stops at the next title so that a second mandate cannot borrow the first
    one's constituency.
    """
    tail = flatten(tail)
    stop = len(tail)
    nxt = CHAMBER_RE.search(tail)
    if nxt:
        stop = min(stop, nxt.start())
    for ch in ";]":
        i = tail.find(ch)
        if i >= 0:
            stop = min(stop, i)
    # A break inside a hyphenated department name is common in the OCR:
    # "depute Hte- Saone (1919-1928)".
    win = re.sub(r"-\s+", "-", tail[:stop])
    m = YEAR_CLUSTER_RE.search(win)
    years = ""
    if m and _dates_a_mandate(win, m):
        years = m.group(0)
    else:
        m = None
    place = ""
    # The date run may sit either side of the constituency, so it is removed
    # before the constituency is read off the front of what remains.
    strip = win if not m else (win[:m.start()] + " " + win[m.end():])
    strip = re.sub(r"^[ \xa0]*[\[(][ \xa0]*", " ", strip)
    c = CONSTITUENCY_RE.match(strip)
    if c:
        cand = normalise_seat(c.group("place"))
        if cand and not NOT_A_SEAT_RE.match(cand):
            place = cand
    return place, years, year_spans(years)


def _subject_before(prefix: str) -> str:
    """The personal name ending `prefix`, or "" if that slot is not a name."""
    prefix = flatten(prefix)
    prefix = re.sub(r"\s*\*\s*$", "", prefix)
    prefix = re.sub(r"(?:\[[^\]]{0,240}\]\s*)+$", "", prefix)
    prefix = prefix.rstrip(" ,")
    m = re.search(rf"(?P<name>{_NAME})\s*(?:\([^)]{{1,40}}\))?\s*$", prefix)
    if not m:
        return ""
    raw = m.group("name").strip()
    # An honorific *inside* the run means the name starts after it, and what
    # came before was a headline or a sentence: "QUESTION A M. SAINT-GERMAIN,
    # depute d'Oran" is a question put to Saint-Germain.
    inner = list(re.finditer(r"(?:\bMM?\.|\bMme|\bMlle|\bMgr|\bMe\b)\s*", raw))
    if inner and inner[-1].end() < len(raw):
        raw = raw[inner[-1].end():].strip()
        had_honorific = True
    else:
        had_honorific = bool(HONORIFIC_RE.search(prefix[:m.start()]))
    if not raw:
        return ""
    head = raw.split()[0].strip(".")
    if NOT_A_SUBJECT_RE.match(strip_accents(head).lower()):
        return ""
    # A run of initials is not a name this stage can key: "G. L. (depute)".
    if not any(len(t.strip(".'’-")) >= 3 and not re.fullmatch(_PARTICLE, t, re.I)
               for t in raw.split()):
        return ""
    if len(raw.split()) == 1 and not had_honorific:
        # A lone surname is only a subject when an honorific introduced it;
        # otherwise it is as likely to be a place or the tail of a firm name.
        return ""
    # "M. Brice (Rene)[1839-1921], depute [...]" is the surname-first register.
    # `parse_person_name` only reorders it when the surname is capitalised, so
    # the reordering happens here while the forename is still in view.
    paren = re.search(r"\(([^)]{1,40})\)\s*$", prefix)
    if paren and strip_accents(paren.group(1).split()[0]).lower() in FORENAMES:
        return f"{paren.group(1)} {raw}"
    return raw


def mentions(text: str):
    """Yield `(pattern, subject_raw, chamber, place, years, spans, minister,
    evidence)` for every mandate the document attributes to a named person."""
    flat = text.replace("\xa0", " ")
    heads = _entry_heads(flat)
    for m in CHAMBER_RE.finditer(flat):
        chamber = CHAMBERS[strip_accents(m.group("chamber")).lower()]
        back = flat[max(0, m.start() - 220):m.start()]
        if kinship_before(back):
            continue
        tail = flat[m.end():m.end() + TAIL_CHARS]
        if FOREIGN_HOUSE_RE.search(flatten(tail)[:40]):
            continue
        if DELEGATE_RE.match(flatten(tail)):
            continue
        place, years, spans = read_tail(tail)
        minister = bool(MINISTER_RE.search(
            flat[max(0, m.start() - 60):m.end() + TAIL_CHARS]))
        ev = flatten(flat[max(0, m.start() - 80):m.end() + 80])

        pattern, subject = "", ""
        # (1) apposition, and (2) the compiler's bracket, which is the same
        # backward look once the bracket run is stripped.
        if back.rstrip().endswith(",") or back.rstrip().endswith("["):
            subject = _subject_before(back.rstrip().rstrip(",["))
            pattern = "bracket" if back.rstrip().endswith("[") else "apposition"
        if not subject and "[" in back[-BRACKET_CHARS:]:
            cut = back.rfind("[")
            if "]" not in back[cut:]:
                subject = _subject_before(back[:cut])
                pattern = "bracket"
        # (3) title first: "le senateur Ernest Feray". Only a recognised
        # forename opens the name, or "depute de la Cochinchine" reads as one.
        if not subject:
            ftail = flatten(tail)
            fwd = re.match(rf"\s+(?:M\.\s*)?(?P<name>{_NAME})", ftail)
            if fwd and re.search(r"(?i)\b(?:le|du|au|ce|notre)\s*$",
                                 flatten(back)[-12:].rstrip(" anciec.")):
                head = fwd.group("name").split()[0].strip(".")
                if strip_accents(head).lower() in FORENAMES:
                    subject, pattern = fwd.group("name").strip(), "title_first"
                    place, years, spans = read_tail(ftail[fwd.end():])
        # (4) the enclosing entry header, for career prose under a footnote or
        # a dictionary entry.
        if not subject:
            h = _head_for(heads, m.start(), flat)
            if h:
                subject, pattern = h, "entry_header"
        if not subject:
            continue
        yield pattern, subject, chamber, place, years, spans, minister, ev


def _entry_heads(flat: str) -> list[tuple[int, int, str]]:
    """`(start, end, name)` for every footnote header that names a person."""
    heads = []
    for m in FOOTNOTE_HEAD_RE.finditer(flat):
        name = m.group("name").strip()
        if HEAD_NOT_PERSON_RE.match(name):
            continue
        if len(re.findall(r"[^\W\d_]{2,}", name)) < 2:
            continue
        heads.append((m.start(), m.end(), name))
    return heads


def _head_for(heads, pos: int, flat: str) -> str:
    """The footnote whose career line contains `pos`, if any.

    Three conditions, all needed: the mandate is after the header, inside its
    character budget, and in the same paragraph. Without the last one a mandate
    named in the article three paragraphs below a footnote is credited to the
    man the footnote is about.
    """
    for start, end, name in reversed(heads):
        if start > pos:
            continue
        if pos >= end + ENTRY_CHARS:
            return ""
        return "" if ENTRY_BREAK_RE.search(flat[end:pos]) else name
    return ""


def load(name):
    with open(os.path.join(PROC, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def network_keys() -> dict[str, str]:
    """Every person key in the network, mapped to its resolved key."""
    out = {}
    for row in load("persons_resolved.csv"):
        pid = row["person_id"]
        out[pid] = pid
        for k in (row.get("merged_keys") or "").split(";"):
            k = k.strip()
            if k:
                out[k] = pid
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=0,
                    help="print this many random rows for hand-checking")
    ap.add_argument("--limit", type=int, default=0, help="first N documents")
    args = ap.parse_args()

    docs = load("documents.csv")
    if args.limit:
        docs = docs[:args.limit]
    keys = network_keys()

    rows, pats, seen = [], collections.Counter(), set()
    for doc in docs:
        text = B.read_text(doc["doc_id"])
        if not text or not CHAMBER_RE.search(text):
            continue
        for (pat, subject, chamber, place, years, spans,
             minister, ev) in mentions(text):
            parsed = parse_person_name(subject)
            if not parsed["person_key"] or not parsed["surname"]:
                continue
            resolved = keys.get(parsed["person_key"], "")
            sig = (doc["doc_id"], resolved or parsed["person_key"], chamber,
                   place, years)
            if sig in seen:
                continue
            seen.add(sig)
            pats[pat] += 1
            rows.append({
                "doc_id": doc["doc_id"],
                "person_key": parsed["person_key"],
                "person_id": resolved,
                "in_network": "1" if resolved else "0",
                "name_clean": parsed["name_clean"],
                "surname": parsed["surname"],
                "given": parsed["given"],
                "chamber": chamber,
                "constituency": place,
                "years_raw": years,
                "year_start": spans[0][0] if spans else "",
                "year_end": spans[-1][1] if spans else "",
                "n_spans": len(spans),
                "also_minister": "1" if minister else "0",
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
    print(f"  by register: {pats.most_common()}", file=sys.stderr)
    print(f"  with a constituency: "
          f"{sum(1 for r in rows if r['constituency']):,}; with dates: "
          f"{sum(1 for r in rows if r['year_start']):,}", file=sys.stderr)

    if args.audit and rows:
        rng = random.Random(5)
        for r in rng.sample(rows, min(args.audit, len(rows))):
            print(f"\n{r['name_clean']} = {r['chamber']}"
                  f" / {r['constituency'] or '-'} / {r['years_raw'] or '-'}"
                  f"  [{r['pattern']}, in_network={r['in_network']}]"
                  f"\n   {r['evidence']}")


if __name__ == "__main__":
    main()
