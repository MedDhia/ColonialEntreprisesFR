"""Stage 3h - the parliamentary rosters.

    python3 src/parse_rosters.py             # -> affiliations_roster.csv
    python3 src/parse_rosters.py --audit 20  # print rows for hand-checking

The compiler keeps one catalogue group of his own making, titled
*Parlementaires interesses directement ou par des proches a des entreprises
privees*, and it holds eight documents: Roger Mennevee's directory
*Parlementaires et financiers* for 1924, 1930, 1932, 1936 and 1954, a press
survey of the 1893 intake, *Les squales coloniaux* (1922), and one on the
Belgian parliament.

These are the only documents in the corpus that are *about* the overlap between
the legislature and the company boards, and until this stage they were almost
unread. The 1924 directory is 89,259 characters and yielded **4 ties**; 1954 is
46,229 characters and yielded **1**. The reason is the entry header. Stage 3e
segments on `SURNAME (Forename)` and Mennevee writes `SURNAME, Forename`:

    D'ANDIGNÉ, Geoffroy (Comte)[1858-1932]
    Député de Maine-et-Loire [1924-1932]
    Adresse : Hôtel d'Orsay, 9, quai d'Orsay, à Paris (VIIe).
    Administrateur :
    Compagnie parisienne de garages automobiles (nommé à l'assemblée du 7
    juillet 1922).

so every entry in three of the five directories fell through, and with it the
`Administrateur :` block underneath. The 1954 volume drops the fielding and
runs the same content as prose:

    ABELIN Pierre, député de la Vienne, M. R.P., Membre de la commission …
    Administrateur de la Société d'Édition des Producteurs agricoles,
    industriels et coloniaux ; de l'Avenir-Publicité ; des Établissements
    Rouzaud …

One header rule covers both: a line whose first token is a capitalised surname
and which has a chamber word within 200 characters. The chamber word is what
makes it a roster entry rather than a headline, and it is also the mandate, so
this stage emits the seat and the term alongside the directorship - the only
stage that can, because it is the only genre where the two sit together.

**"ou par des proches" is in the group's own title, and it is a trap.** Mennevee
tracks the proxy holding as carefully as the direct one, so a roster entry is
part career and part genealogy, and the companies in the genealogy are not the
parliamentarian's:

    Frère cadet de Paul-Jonas et Gaston Hesse, gérants des Comptoirs Hesse
    belle-mère de Lucien Bach, administrateur de la Société générale foncière
    Père de François André-Hesse, administrateur de la Société générale foncière

Reading those as the deputy's own directorships would manufacture exactly the
interlocks the document is careful to distinguish. Every role phrase is
therefore tested against the clause it sits in, and a kinship word in that
clause redirects the tie: the person becomes the *relative*, `held_by` becomes
`relative`, and `related_to` records the parliamentarian it was reached
through. Dropping them instead would throw away the prete-nom structure the
group exists to document; merging them silently would corrupt the board.

Excluded: `empire-oligarchie-belge-1930`, which is the Belgian parliament. The
men are real and the boards are real, but a seat in the Chambre des
representants is not a seat in the body that legislated for the French empire,
and the column would silently mean two things.
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
from common import (FORENAMES, PLACES, clean_text, ensure_dir,  # noqa: E402
                    strip_accents)
from names import parse_person_name  # noqa: E402
from parse_ties import canonical_role  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(PROC, "affiliations_roster.csv")
OUT_MANDATES = os.path.join(PROC, "roster_mandates.csv")

GROUP = "Parlementaires intéressés"
EXCLUDE = {"empire-oligarchie-belge-1930-1b9a1a"}

CONFIRM_CHARS = 200     # how far past a header line the chamber word may sit
MAX_ENTRY_CHARS = 5000  # an entry longer than this lost its boundary
MIN_ENTRY_CHARS = 40    # two headers closer than this are one header misread
MAX_BLOCK_CHARS = 900   # longest role-labelled company list read as one block
MIN_HEAD_CAPS = 3       # shortest all-capitals surname trusted as a header
MIN_FIRM_TOKENS = 2     # a resolved firm name shorter than this is degenerate

# A roster entry starts at a line, or after a full stop - see `head_offsets`.
# The 1924 volume is a Journal officiel transcript of the directory being read
# aloud from the tribune, so an entry can also open after the shorthand
# writer's dash, and the deputy reading it prefixes some names with "M." and
# some not: "M. Georges Lévy. — Berthelot (André), sénateur de la Seine",
# "M. HELMER, Albert-Paul", "M. de MUN, Bertrand (Comte)".
ANCHOR_RE = re.compile(
    r"(?m)(?:^|(?<=[.!?])[ \n\t])[ \t«\"—–]*"
    r"(?:MM?\.|Mme|Mlle|[Mm]onsieur|[Mm]adame|[Mm]essieurs)?[ \t]*"
    # "Le duc d'Audiffret-Pasquier, depute de l'Orne. Administrateur des mines
    # d'Anzin." Missing this form did not just lose the duke: his board was
    # credited to whichever entry the sentence fell inside.
    r"(?:(?:[Ll]e|[Ll]a)[ \t]+(?:duc|baron|comte|vicomte|marquis|g[eé]n[eé]ral|"
    r"colonel|commandant|docteur|pr[eé]sident|b[aâ]tonnier)[ \t]+)?"
    # The particle is *not* consumed here: it is part of the surname, and
    # stripping it turned "De WENDEL, François" into François Wendel. It is an
    # optional leading element of the header patterns instead.
    r"")

CONFIRM_TIGHT = 60      # for the weakest header form - see PLAIN_HEAD_RE

# Company names sit at line start too, inside the compiler's own bracketed
# asides, and one of them - "Caoutchoucs de Phuoc-Hoa (1927), administrateur
# des Caoutchoucs de Kompong-Thom" - was read as a parliamentarian called
# "1927 Caoutchoucs de Phuoc-Hoa".
FIRM_HEAD_RE = re.compile(
    r"(?i)^\[?\s*(?:soci[eé]t[eé]|cie|compagnie|banque|mines?|"
    r"caoutchoucs?|plantations?|[eé]tablissements?|[eé]ts|comptoirs?|"
    r"chemins?\s+de\s+fer|forges?|usines?|manufactures?|sucreries?|"
    r"papeteries?|distilleries?|brasseries?|chantiers?|ateliers?|"
    r"charbonnages?|houill[eè]res?|p[eé]troles?|[eé]tains?|"
    r"union|consortium|syndicat|groupe|omnium|crédit|cr[eé]dit|"
    r"assurances?|immobili[eè]re|fonci[eè]re|agricole|domaines?|"
    r"canal|caisse|office|agence|messageries?|"
    r"[eé]nergie|forces?\s+motrices|tramways?|docks?|ports?)\b")

# The roster's role vocabulary is stage 3e's plus the two verb forms the 1924
# transcript uses, where the deputy reading aloud says what a man does rather
# than naming his title: "Berthelot (André), senateur de la Seine, preside ou
# administre : le Metropolitain de Paris, la Compagnie du chemin de fer …"
ROLE = rf"{B.ROLE}|pr[eé]side(?:\s+ou\s+administre)?|administre"
ROLE_LABEL_RE = re.compile(rf"\b(?P<role>{ROLE})s?\s*:", re.I)
GOVERNED_RE = re.compile(
    rf"\b(?P<role>{ROLE})\s+(?:de\s+la|de\s+l['’]|du|des|de|d['’])\s*"
    rf"(?P<name>[^,;.\n]{{4,90}})", re.I)

# An entry that names no role at all, because the chamber line's own colon
# introduces the boards: "Touron, senateur de l'Aisne : Pates, papiers et
# textiloses ; Forces motrices de la Tuyere." The document exists to list
# directorships, so an unlabelled list is read as one - but only where the
# entry carries no role label anywhere, so a labelled entry is never widened.
BARE_LIST_RE = re.compile(r"[ \t]*[:;][ \t]*")

# What ends a role block: the next fielded label, whatever it is. The register
# has more labels than it has roles - "Adresse :", "Membre de :", "Intéressé :",
# "Liquidateur :", "Propriétaire des journaux :" - and bounding the block only
# at the labels this stage keeps let one run into the next: Patenotre's
# "Administrateur :" list ran on through "Propriétaire des journaux : Le Petit
# Niçois, Le Petit Var, La Sarthe" and made him a director of three newspapers
# and of a company called Sarthe.
# The label's own spacing is the compiler's typesetting, non-breaking spaces
# included - "Propriétaire des journaux\xa0 :" - so the whitespace classes here
# are `\s`, not `[ \t]`.
BLOCK_END_RE = re.compile(
    r"(?m)(?:^|(?<=[.\n]))[ \t\xa0]*"
    r"[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-\xa0 ]{3,44}\s*:")

# A header line's first token. The rosters capitalise the surname throughout,
# including the particle: "D'ANDIGNÉ", "AMIDIEU DU CLOS", "ASTIER de la
# VIGERIE". The 1924 volume is the exception and writes it mixed-case with the
# forename parenthesised: "Accambray (Léon), député de l'Aisne."
_HEAD_PARTICLE = r"(?:[Dd]e|[Dd]u|[Dd]es|[Dd][’']|[Vv]on|[Vv]an)"
CAPS_HEAD_RE = re.compile(
    rf"^\[?\s*(?P<caps>(?:{_HEAD_PARTICLE}[ \xa0])?"
    r"[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ'’\-]{2,}"
    r"(?:[ \xa0](?:de|du|des|d[’']|la|le|von|van)?[ \xa0]?"
    r"[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ'’\-]+){0,3})")
MIXED_HEAD_RE = re.compile(
    r"^\[?\s*(?P<name>[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]+"
    r"(?:[ \xa0](?:de|du|des|d[’'])[ \xa0]?[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]+){0,2})"
    r"\s*\[?\(\s*(?P<given>[^)\n]{1,40})\)")

# The weakest header form, and the 1924 transcript is full of it: a surname on
# its own, mixed-case, with no forename at all - "Cosnier, sénateur de l'Indre",
# "Touron, sénateur de l'Aisne", "De Saint-Quentin, sénateur du Calvados". It is
# only trusted when the chamber word follows within CONFIRM_TIGHT characters,
# which is the roster's own layout and not something running prose does.
PLAIN_HEAD_RE = re.compile(
    r"^\[?\s*(?P<name>[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]{2,}"
    r"(?:[ \xa0](?:de|du|des|d[’'])?[ \xa0]?[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]+){0,2})"
    r"\s*(?:\[[^\]\n]{0,30}\]\s*)?,")

# Lines that open with a capital and carry a chamber word nearby without being
# an entry header: the roster's own field labels, and its running matter.
NOT_A_HEAD_RE = re.compile(
    r"(?i)^\[?\s*(?:d[eé]put[eé]|s[eé]nateur|s[eé]natrice|adresses?|"
    rf"{B.ROLE}|ministre|membre|ancien|anc\.|n[eé]\s|d[eé]c[eé]d[eé]|"
    r"mari[eé]|[eé]poux|fr[eé]re|s[oœ]ur|p[eè]re|m[eè]re|fils|fille|"
    r"beau-|belle-|dont|voir|cf\.|note|sciences|battu|[eé]lu|r[eé][eé]lu|"
    r"groupe|commission|assembl[eé]e|s[eé]nat|chambre|conseil|"
    r"nota|source|table|index|sommaire|suite|fin|"
    # "Nos Députés" is a section heading, and it passed every other test
    # because the heading's own word is the chamber word that confirms it.
    r"nos|notre|mes|ses|leurs|votre|quelques|certains|plusieurs|tous|"
    r"deux|trois|quatre|voici|voil[aà]|parmi|entre|chez)\b")

# The compiler's genealogical connective. "Dont Henri Hirsch, administrateur de
# …" introduces a son, and `KINSHIP_RE` has no word for it because "dont" is an
# ordinary relative pronoun everywhere else in the corpus; here, capitalised
# and followed by a name, it is a kinship marker.
DONT_RE = re.compile(r"\bDont\s+[A-ZÉÈÀÂÎÔÛÇ]")

# A forename-led personal name anywhere in running text. Requiring the
# forename is what separates a person from a firm: the clause a kinship word
# opens is full of both - "puis des Plantations réunies de Mimot, administrateur
# des Manufactures indochinoises de cigarettes" - and the nearest capitalised
# run before the role word is as often the previous company as the man.
PERSON_RUN_RE = re.compile(
    r"[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]+"
    r"(?:[ \xa0](?:de|du|des|d[’'la])?[ \xa0]?[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]+){1,3}")

# Fragments a company list yields that are not companies: a date, a bare note,
# an address, a parliamentary group.
# A lower-case fragment that does open a new board rather than continuing the
# previous one, because the register writes the article: "preside ou administre
# : le Metropolitain de Paris, la Compagnie du chemin de fer du bois de
# Boulogne"; "administrateur de la Societe X ; de l'Avenir-Publicite".
NEW_ITEM_RE = re.compile(
    r"(?i)^(?:et\s+)?(?:de\s+la|de\s+l['’]|du|des|de|d['’]|"
    r"la|le|les|l['’])\s*[A-ZÉÈÀÂÎÔÛÇ]")

NOT_A_FIRM_RE = re.compile(
    r"(?i)^(?:\d|[ivxlc]+$|n[oº°]|p\.|pp\.|voir|idem|ibid|etc|"
    r"nomm[eé]|d[eé]missionn|depuis|jusqu|en\s+\d|"
    r"rue\b|avenue\b|boulevard\b|quai\b|place\b|"
    r"m\.\s*r\.\s*p|r\.\s*i\b|s\.\s*f\.\s*i\.\s*o|u\.\s*d\.\s*s\.\s*r)")

SNAPSHOT_RE = re.compile(r"-(1[89]\d\d)-")

# A place followed by a date is where a letter was written, not a man.
DATESTAMP_RE = re.compile(
    r"(?i)^\[?\s*[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\- ]{2,24},\s*le\s+\d{1,2}\b")


_PARTICLES = ("de", "du", "des", "d’", "d'", "la", "le", "von", "van")


def titlecase_surname(caps: str) -> str:
    """"AMIDIEU DU CLOS" -> "Amidieu du Clos"; particles stay lower.

    An elided particle is one token with the name it governs - `D'ANDIGNÉ` -
    and has to be split on the apostrophe or the whole surname capitalises as
    "D'andigné".
    """
    out = []
    for i, word in enumerate(caps.split()):
        low = strip_accents(word).lower()
        if low in _PARTICLES:
            out.append(low.replace("d'", "d’"))
            continue
        m = re.match(r"(?i)^(d[’'])(?P<rest>.+)$", word)
        if m and strip_accents(m.group(1)).lower() in ("d’", "d'"):
            out.append("d’" + "-".join(p.capitalize()
                                       for p in m.group("rest").split("-")))
            continue
        out.append("-".join(p.capitalize() for p in word.split("-")))
    return " ".join(out)


def parse_roster_head(line: str) -> str:
    """The personal name a roster header line carries, in "Given Surname" form.

    Six shapes occur and all six reduce to a capitalised surname plus at most
    one forename: "ANQUETIL, Paul", "D'ANDIGNÉ, Geoffroy (Comte)[1858-1932]",
    "ANDRÉ-HESSE Olry (1874-1940)", "ABELIN Pierre, député de la Vienne",
    "D'ANDLAU" and the 1924 volume's "Accambray (Léon),".
    """
    head = line
    ch = M.CHAMBER_RE.search(head)
    if ch:
        head = head[:ch.start()]
    head = re.sub(r"\[[^\]]*\]", " ", head)
    head = re.sub(r"\((?![^)]{0,40}\))", " ", head)
    head = head.strip(" ,;.\t[]")

    mixed = MIXED_HEAD_RE.match(head)
    caps = CAPS_HEAD_RE.match(head)
    if mixed and not _given_plausible(mixed.group("given")):
        # "Succursale : 27 bis, r. du Vieux-Faubourg, Lille (Nord)." parses as
        # a man named Nord Lille, and the deputy three lines below confirmed
        # him. What is in the parentheses has to be a forename, a title or a
        # life date - it is never a department.
        mixed = None
    if mixed and (not caps or len(mixed.group("name")) > len(caps.group("caps"))):
        given = mixed.group("given").split(",")[0].strip()
        return f"{given} {mixed.group('name')}".strip()
    if not caps:
        plain = PLAIN_HEAD_RE.match(head + ",")
        return plain.group("name").strip() if plain else ""
    surname = titlecase_surname(caps.group("caps"))
    rest = head[caps.end():].strip(" ,;.")
    # "(Comte)", "(Général)", "(Baron d')" are titles, not forenames. The
    # forename list is seeded from the catalogue and does not hold every one
    # the rosters use - "RATIER, Antony" left a man with no forename at all -
    # so an unrecognised capitalised word is taken once the titles are out.
    given, fallback = "", ""
    for cand in re.findall(r"[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]+", rest):
        if TITLE_WORD_RE.match(strip_accents(cand).lower()):
            continue
        if strip_accents(cand.split("-")[0]).lower() in FORENAMES:
            given = cand
            break
        fallback = fallback or cand
    return f"{given or fallback} {surname}".strip()


TITLE_WORD_RE = re.compile(
    r"^(?:comte|comtesse|baron|baronne|vicomte|marquis|duc|duchesse|"
    r"general|colonel|commandant|capitaine|amiral|docteur|professeur|"
    r"chevalier|officier|commandeur|prince|abbe|monseigneur|"
    r"depute|senateur|ministre|president|maire|avocat|"
    r"adresse|adresses|administrateur|membre|ancien|anc)$")


def _given_plausible(given: str) -> bool:
    """Whether a parenthesised header field can be a forename."""
    given = given.strip()
    if re.search(r"\b(?:1[6-9]\d\d|20\d\d)\b", given):
        return True
    first = strip_accents(given.split(",")[0].split()[0] if given.split()
                          else "").lower()
    return bool(first) and (first.split("-")[0] in FORENAMES
                            or bool(TITLE_WORD_RE.match(first)))


def head_offsets(text: str) -> list[tuple[int, str]]:
    """`(offset, name)` for every position that opens a roster entry."""
    return [(s, n) for s, n, confirmed in candidates(text) if confirmed]


def candidates(text: str) -> list[tuple[int, str, bool]]:
    """`(offset, name, confirmed)` for every header-shaped position.

    A position is *confirmed* - it opens an entry this stage will read - only
    when a chamber word follows within the confirm window. An unconfirmed
    candidate still ends the entry above it, and it has to: Albert Lebrun's
    1936 entry names no chamber at all, because by then he was President of the
    Republic, and without a boundary there his board joined the entry before
    his. Only the strong header form is trusted as a boundary, and only at a
    line start, so a company name inside a list cannot cut a list short.

    Anchored at a line start *or* after a full stop. The 1924 and 1954 volumes
    run their entries together as prose - "Accambray (Léon), député de l'Aisne.
    Administrateur de la Compagnie céramique française … Amic (Jean), sénateur
    des Alpes-Maritimes, administrateur de …" - so a line-anchored rule found
    90 entries in a document holding several hundred, and every entry it missed
    had its boards credited to whichever entry it fell inside.
    """
    out = []
    for anchor in ANCHOR_RE.finditer(text):
        start = anchor.end()
        line = text[start:start + 120].split("\n")[0].strip()
        if not line or NOT_A_HEAD_RE.match(line) or FIRM_HEAD_RE.match(line):
            continue
        # "Paris, le 11 juillet 1924." is a letter's datestamp, and the
        # senator it is addressed to sits close enough to confirm it.
        if DATESTAMP_RE.match(line):
            continue
        caps, mixed = CAPS_HEAD_RE.match(line), MIXED_HEAD_RE.match(line)
        plain = PLAIN_HEAD_RE.match(line)
        if not caps and not mixed and not plain:
            continue
        if caps and len(caps.group("caps").replace(" ", "")) < MIN_HEAD_CAPS:
            caps = None
        window = CONFIRM_CHARS if (caps or mixed) else CONFIRM_TIGHT
        confirmed = bool(M.CHAMBER_RE.search(text[start:start + window]))
        line_start = start == 0 or text[start - 1] == "\n"
        if not confirmed and not (caps and line_start):
            continue
        name = parse_roster_head(line)
        # The headline test belongs on the name, not on the line. Applied to
        # the line it rejected "Binder (Maurice), député des Landes,
        # administrateur : Banque française *pour* le Brésil" - and Binder's
        # whole board then went to the entry above his.
        words = {strip_accents(w).lower()
                 for w in re.findall(r"[^\W\d_]{2,}", name or "")}
        if words & B.HEADLINE_WORDS:
            continue
        if name and M.CHAMBER_RE.search(name):
            continue      # the "name" is the chamber word itself
        # A one-word "surname" that is a place name in the geocoder's
        # gazetteer is a heading or an address, not a parliamentarian.
        if name and len(name.split()) == 1 \
                and strip_accents(name).lower() in PLACES:
            continue
        if name and not re.search(r"\d", name):
            if out and start - out[-1][0] < MIN_ENTRY_CHARS:
                continue
            out.append((start, name, confirmed))
    return out


def entries(text: str):
    """Yield `(name, body)` for every roster entry in one document."""
    cands = candidates(text)
    for i, (start, name, confirmed) in enumerate(cands):
        if not confirmed:
            continue
        end = cands[i + 1][0] if i + 1 < len(cands) else len(text)
        yield name, text[start:min(end, start + MAX_ENTRY_CHARS)]


def mandate_of(body: str) -> tuple[str, str, str]:
    """`(chamber, seat, years)` from the chamber line of an entry."""
    m = M.CHAMBER_RE.search(body[:CONFIRM_CHARS * 2])
    if not m:
        return "", "", ""
    chamber = M.CHAMBERS[strip_accents(m.group("chamber")).lower()]
    seat, years, _ = M.read_tail(body[m.end():m.end() + M.TAIL_CHARS])
    return chamber, seat, years


def _rejoin(parts: list[str]) -> list[str]:
    """Glue back the fragments a comma inside a company name split apart.

    The roster separates boards with commas, and company names contain commas:
    "Association industrielle, commerciale et financière" became a firm called
    "commerciale et financière", which resolved to a bank; "Manufacture de
    Tabacs, Cigares et Cigarettes J. Bastos" became "Manufacture de Tabacs",
    which resolved to a different tobacco company. A new board never starts
    with a lower-case word, so a fragment that does is a continuation.
    """
    out: list[str] = []
    for part in parts:
        bare = part.strip(" .,;:«»\"'")
        first = bare[:1]
        continues = (out and first and not first.isupper()
                     and not first.isdigit()
                     and not NEW_ITEM_RE.match(bare))
        if continues:
            out[-1] = f"{out[-1]}, {part.strip()}"
        else:
            out.append(part)
    return out


def _items(block: str) -> list[str]:
    """Company names from one role block."""
    out = []
    for part in _rejoin(B.split_list(block)):
        part = re.sub(r"(?i)^(?:et\s+)?(?:de\s+la|de\s+l[’']|du|des|de|d[’'])\s*",
                      "", part).strip(" .,;:«»\"'")
        part = clean_text(part)
        if len(part) < 5 or NOT_A_FIRM_RE.match(part):
            continue
        out.append(part)
    return out


def affiliations_in(body: str):
    """Yield `(role, company, kinship, relative)` for one roster entry.

    A role phrase inside a clause governed by a kinship word belongs to the
    relative, and is returned with that relative's name so the caller can key
    the tie to them instead of to the parliamentarian.
    """
    labelled = ROLE_LABEL_RE.search(body) or GOVERNED_RE.search(body)
    if not labelled:
        ch = M.CHAMBER_RE.search(body[:CONFIRM_CHARS])
        seat_end = ch.end() + len(M.read_tail(
            body[ch.end():ch.end() + M.TAIL_CHARS])[0]) if ch else 0
        colon = BARE_LIST_RE.search(body, seat_end) if ch else None
        if colon and colon.start() - seat_end < 40:
            block = body[colon.end():colon.end() + MAX_BLOCK_CHARS]
            # With no role label to anchor on there is nothing to test a
            # kinship clause against per item, so the list simply stops where
            # the genealogy starts: "Bataille (Victor), député du Cantal :
            # marié à Geneviève Rocca, fille d'Émilien Rocca, … des Éts Rocca"
            # is his wife's family firm, not his board.
            kin = M.KINSHIP_RE.search(block) or DONT_RE.search(block)
            if kin:
                block = block[:kin.start()]
            end = BLOCK_END_RE.search(block)
            for name in _items(block[:end.start()] if end else block):
                yield "administrateur", name, "", ""
        return
    for m in ROLE_LABEL_RE.finditer(body):
        role = canonical_role(m.group("role")) or "administrateur"
        nxt = ROLE_LABEL_RE.search(body, m.end())
        end = BLOCK_END_RE.search(body, m.end())
        stop = min(nxt.start() if nxt else len(body),
                   end.start() if end else len(body),
                   m.end() + MAX_BLOCK_CHARS)
        para = re.search(r"\n[ \t]*\n", body[m.end():stop])
        if para:
            stop = m.end() + para.start()
        kin, who = _kinship_at(body, m.start())
        for name in _items(body[m.end():stop]):
            yield role, name, kin, who
    for m in GOVERNED_RE.finditer(body):
        role = canonical_role(m.group("role")) or "administrateur"
        kin, who = _kinship_at(body, m.start())
        name = clean_text(re.sub(r"\([^)]*\)", " ", m.group("name")))
        name = name.strip(" .,;:«»\"'")
        if len(name) >= 5 and not NOT_A_FIRM_RE.match(name):
            yield role, name, kin, who
        # "administrateur de X ; de Y ; des Z" - the role governs the whole
        # semicolon run, which is how the 1954 volume writes a board list.
        rest = body[m.end():m.end() + MAX_BLOCK_CHARS]
        rest = rest[:rest.find("\n\n")] if "\n\n" in rest else rest
        for chunk in re.split(r"\s*;\s*", rest)[1:]:
            if not re.match(r"(?i)\s*(?:de\s+la|de\s+l[’']|du|des|de|d[’'])\s",
                            chunk):
                break
            for name in _items(chunk):
                yield role, name, kin, who


def _kinship_at(body: str, pos: int) -> tuple[str, str]:
    """`(kinship word, relative)` if a kinship clause governs `pos`.

    The relative is the name the role phrase is in apposition to, which is the
    *last* name in the clause and not the first. "Sa fille Lina a épousé en
    1930 le banquier Jean Rheims, administrateur des Manufactures
    indochinoises de cigarettes" is Rheims's directorship, not Lina's.
    """
    window = M.flatten(body[max(0, pos - 240):pos])
    clause = M.clause_before(window)
    kin = M.KINSHIP_RE.search(clause)
    dont = DONT_RE.search(clause)
    if not kin and not dont:
        return "", ""
    word = kin.group(0).lower().strip() if kin else "dont"
    return word, _last_person(clause) or _last_person(window)


def _last_person(segment: str) -> str:
    """The last forename-led personal name in `segment`.

    Token-by-token rather than by whole match, because the connective before
    the name is capitalised too: `finditer` on "Dont Henri Hirsch," returns one
    match starting at "Dont", whose first word is not a forename, and the
    person inside it was never seen.
    """
    words = list(re.finditer(r"[A-ZÉÈÀÂÎÔÛÇ][A-Za-zÀ-ÿ’'\-]+|[a-zà-ÿ’']+", segment))
    for i in range(len(words) - 1, -1, -1):
        token = words[i].group(0)
        if strip_accents(token.split("-")[0]).lower() not in FORENAMES:
            continue
        if not token[:1].isupper():
            continue
        end = i
        while end + 1 < len(words):
            nxt = words[end + 1].group(0)
            if nxt[:1].isupper() or strip_accents(nxt).lower() in (
                    "de", "du", "des", "d’", "d'", "la", "le", "van", "von"):
                end += 1
            else:
                break
        if end > i:
            return segment[words[i].start():words[end].end()].strip()
    return ""


def firm_plausible(raw: str, resolved: str) -> bool:
    """Whether a resolved company name can be the firm the phrase named.

    The resolver was audited on abbreviated colonial company names and it is
    matching, here, against a roster full of metropolitan firms the catalogue
    does not hold. Two of its error modes are cheap to catch: it collapses a
    named firm onto a one-word catalogue entry ("Société générale d'armement"
    -> "ARMEMENT"), and it matches on generic words alone. Requiring a shared
    distinctive word, and a resolved name with something in it, removes both
    without touching the matcher other genres depend on.
    """
    def words(s):
        return {w for w in re.findall(r"[^\W\d_]{3,}", strip_accents(s).lower())
                if w not in GENERIC_WORDS}
    rw, cw = words(raw), words(resolved)
    if len(cw) < MIN_FIRM_TOKENS and len(rw) >= MIN_FIRM_TOKENS + 1:
        return False
    # The catalogue holds its own section headings as if they were firms, so
    # "Société générale d'armement" resolves to "ARMEMENT" and a bare
    # "charbonnages" to "CHARBONNAGES". A name that reduces to one industry
    # noun is a heading, not a company.
    if len(cw) == 1 and cw <= SECTION_WORDS:
        return False
    # A territory in the name is never incidental in this catalogue, so it is
    # never droppable: "Crédit mobilier indochinois" resolving to "Crédit
    # mobilier français" shares both distinctive words and is still a different
    # firm on a different continent.
    terr = rw & TERRITORY_WORDS
    if terr and not (terr & cw):
        return False
    return bool(rw & cw) or not rw


# Territorial adjectives and place words. The list is the dimension the whole
# dataset is organised by, which is exactly why a mismatch here is fatal
# rather than cosmetic.
TERRITORY_WORDS = {
    "indochinois", "indochinoise", "indochine", "tonkinois", "tonkin",
    "annamite", "annam", "cochinchinois", "cochinchine", "cambodgien",
    "cambodge", "laotien", "laos", "marocain", "marocaine", "maroc",
    "algerien", "algerienne", "algerie", "tunisien", "tunisienne", "tunisie",
    "africain", "africaine", "afrique", "malgache", "madagascar",
    "senegalais", "senegal", "guineen", "guinee", "dahomeen", "dahomey",
    "soudanais", "soudan", "congolais", "congo", "gabonais", "gabon",
    "camerounais", "cameroun", "togolais", "togo", "calédonien",
    "caledonien", "caledonie", "tahitien", "oceanien", "oceanie",
    "antillais", "martinique", "guadeloupe", "guyane", "reunion",
    "syrien", "syrie", "libanais", "liban", "levantin", "chinois", "chine",
    "egyptien", "egypte", "orientale", "occidentale", "equatoriale",
    "belge", "britannique", "ottomane", "russe",
}


# The catalogue's own section headings, which sit in the company list looking
# like firms because that is where the compiler filed them.
SECTION_WORDS = {
    "armement", "charbonnages", "houilleres", "forges", "mines", "minerais",
    "banque", "banques", "assurances", "assurance", "navigation", "transports",
    "sucreries", "plantations", "caoutchoucs", "tabacs", "textiles", "coton",
    "electricite", "gaz", "eaux", "hotels", "presse", "journaux", "papeteries",
    "brasseries", "distilleries", "ciments", "phosphates", "petroles",
    "chemins", "tramways", "ports", "docks", "peches", "elevage", "cafe",
}

GENERIC_WORDS = {
    "societe", "cie", "compagnie", "generale", "general", "generales",
    "francaise", "francais", "nouvelle", "nouveau", "anciens", "ancienne",
    "etablissements", "ets", "reunies", "reunis", "union", "des", "les",
    "coloniale", "coloniales", "colonial", "industrielle", "industriel",
    "commerciale", "commercial", "agricole", "anonyme", "immobiliere",
    "financiere", "internationale", "nationale", "europeenne", "centrale",
}


def load(name):
    with open(os.path.join(PROC, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", type=int, default=0)
    args = ap.parse_args()

    docs = [d for d in load("documents.csv")
            if GROUP in (d.get("group_path") or "")
            and d["doc_id"] not in EXCLUDE]
    index = B.build_index(load("companies.csv"))
    by_first: dict[str, list[int]] = collections.defaultdict(list)
    for i, (_, _, toks) in enumerate(index):
        for t in set(B.content(toks) or toks):
            by_first[t[:2]].append(i)

    rows, reasons, per_doc = [], collections.Counter(), collections.Counter()
    mandates: list[dict] = []
    for doc in docs:
        text = B.read_text(doc["doc_id"])
        if not text:
            continue
        snap = SNAPSHOT_RE.search(doc["doc_id"])
        year = snap.group(1) if snap else ""
        for person_raw, body in entries(text):
            chamber, seat, years = mandate_of(body)
            n_firms = 0
            head = parse_person_name(person_raw)
            if chamber and head["person_key"]:
                mandates.append({
                    "doc_id": doc["doc_id"],
                    "snapshot_year": year,
                    "person_key": head["person_key"],
                    "name_clean": head["name_clean"],
                    "surname": head["surname"],
                    "given": head["given"],
                    "chamber": chamber,
                    "constituency": seat,
                    "years_raw": years,
                    "year_start": (M.year_spans(years) or [("", "")])[0][0],
                    "year_end": (M.year_spans(years) or [("", "")])[-1][1],
                    "n_firms": 0,
                    "source_ref": doc["name_normalised"] or doc["name_listed"],
                })
            for role, cname, kin, who in affiliations_in(body):
                holder = who if kin and who else person_raw
                parsed = parse_person_name(holder)
                if not parsed["person_key"]:
                    continue
                cid, resolved, method = B.resolve(cname, index, by_first)
                reasons[method] += 1
                if not cid:
                    continue
                if not firm_plausible(cname, resolved):
                    reasons["implausible"] += 1
                    continue
                per_doc[doc["doc_id"]] += 1
                if not (kin and who):
                    n_firms += 1
                    if mandates and (mandates[-1]["person_key"]
                                     == head["person_key"]):
                        mandates[-1]["n_firms"] = n_firms
                rows.append({
                    "doc_id": doc["doc_id"],
                    "company_key": cid,
                    "company_name": resolved,
                    "person_key": parsed["person_key"],
                    "name_clean": parsed["name_clean"],
                    "surname": parsed["surname"],
                    "given": parsed["given"],
                    "role": role,
                    "year": year,
                    "snapshot_year": year,
                    "held_by": "relative" if kin and who else "self",
                    "kinship": kin if kin and who else "",
                    "related_to": person_raw if kin and who else "",
                    "chamber": chamber,
                    "constituency": seat,
                    "mandate_years": years,
                    "source_ref": doc["name_normalised"] or doc["name_listed"],
                    "annotation": cname[:120],
                    "region": doc.get("region", ""),
                    "country": doc.get("country", ""),
                    "sector": doc.get("sector", ""),
                    "anchor_type": "roster_entry",
                    "trigger": "roster",
                    "parse_note": parsed.get("parse_note", ""),
                    "member_raw": holder,
                    "match_method": method,
                    "source_genre": "roster",
                })

    ensure_dir(PROC)
    fields = list(rows[0].keys()) if rows else ["doc_id"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # The mandate rows outnumber the tie rows several times over, because most
    # of a roster's entries name a seat and a term but no firm this catalogue
    # holds. They are the population the continuity analysis needs.
    with open(OUT_MANDATES, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(mandates[0].keys())
                           if mandates else ["doc_id"])
        w.writeheader()
        w.writerows(mandates)
    print(f"wrote {os.path.relpath(OUT_MANDATES, ROOT)}: {len(mandates):,} "
          f"entries, {len({m['person_key'] for m in mandates}):,} people, "
          f"{sum(1 for m in mandates if m['n_firms']):,} with a firm",
          file=sys.stderr)

    own = [r for r in rows if r["held_by"] == "self"]
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(rows):,} ties, "
          f"{len({r['person_key'] for r in rows}):,} people, "
          f"{len({r['company_key'] for r in rows}):,} firms", file=sys.stderr)
    print(f"  held directly: {len(own):,}; through a relative: "
          f"{len(rows) - len(own):,}", file=sys.stderr)
    print(f"  with a chamber: {sum(1 for r in rows if r['chamber']):,}; "
          f"with a seat: {sum(1 for r in rows if r['constituency']):,}",
          file=sys.stderr)
    print(f"  resolution: {reasons.most_common(5)}", file=sys.stderr)
    for doc_id, n in per_doc.most_common():
        print(f"  {n:7,}  {doc_id}", file=sys.stderr)

    if args.audit and rows:
        rng = random.Random(5)
        for r in rng.sample(rows, min(args.audit, len(rows))):
            via = (f" via {r['kinship']} of {r['related_to']}"
                   if r["held_by"] == "relative" else "")
            print(f"\n{r['name_clean']} = {r['role']} of {r['company_name']}"
                  f"{via}\n   raw: {r['annotation']}"
                  f"\n   mandate: {r['chamber'] or '-'} / "
                  f"{r['constituency'] or '-'} / {r['mandate_years'] or '-'}"
                  f"  [{r['snapshot_year']}, {r['match_method']}]")


if __name__ == "__main__":
    main()
