"""Stage 3 - extract companies, people and board ties from the document text.

Each monograph PDF compiles dated extracts about one firm; each *annuaire*
PDF is a directory listing many firms for a single year. Both state boards in
a recognisable register, so the parser works in two passes:

1. Segment a document at its *anchors*. An anchor is anything that fixes a
   date, a source, or a company:

       (La Journee industrielle, 22 mars 1927)      dated press extract
       AEC 1922-519 - Ste generale des abattoirs    inline directory entry
       Annuaire Desfosses, 1945, p. 765             inline directory entry
       89 - Banque commerciale du Maroc,            numbered directory entry
       ANNUAIRE DES ENTREPRISES COLONIALES, 1937    directory header

   Text between one anchor and the next inherits that anchor's year, source
   and company. This is what makes the ties dateable, which is the difference
   between a static name list and a panel usable for network analysis.

2. Within each segment, find board list triggers ("Conseil. -",
   "CONSEIL D'ADMINISTRATION", "Commissaires aux comptes :") and parse the
   list into (person, role) pairs.

Board members that are companies rather than people are kept as such: a
corporate directorship is a company-to-company tie and is written to
org_affiliations.csv, not to affiliations.csv.

Outputs (data/processed/)
    affiliations.csv       person -> company ties, one row per observation
    org_affiliations.csv   company -> company board ties
    persons.csv            distinct people, with name variants
    companies.csv          distinct companies, catalogue + directory entries
    company_attributes.csv capital / founding date / head office observations
    doc_references.csv     document -> document cross-references
    parse_report.csv       per-document parse diagnostics
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import PLACES, clean_text, ensure_dir, plausible_year, strip_accents  # noqa: E402
from names import (  # noqa: E402
    ACCOUNTING_RE,
    LEADING_MM_RE,
    PUBLICATION_RE,
    looks_like_org,
    normalise_org_name,
    org_key,
    parse_person_name,
    tidy_fragment,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC_DIR = os.path.join(ROOT, "data", "processed")
TEXT_DIR = os.path.join(ROOT, "data", "text")

YEAR = r"1[5-9]\d{2}|20\d{2}"

# --- roles ---------------------------------------------------------------
# Ordered most specific first; the first match wins.
ROLE_RULES: list[tuple[str, str]] = [
    (r"pr[eé]sident[- ]?directeur[- ]g[eé]n[eé]ral|p\.?-?d\.?-?g\.?\b|pdt\.?-?dir\.?|"
     r"pr[eé]sid\.?-?dir\.?", "president_directeur_general"),
    (r"vice-?pr[eé]sident[s]?|vice-?pr[eé]sid\.?|v\.?-?pr[eé]sid\.?|vice-?pr[eé]s\.?", "vice_president"),
    # "pres." keeps its period: bare "pres" is the preposition "pres de".
    (r"pr[eé]sident[e]?[s]?\b|pr[eé]sid\.?|pr[eé]st\.?|\bpdt\.?\b|\bpr[eé]s\.", "president"),
    (r"administrateur[s]?[- ]d[eé]l[eé]gu[eé][es]?|adm(?:in)?\.?[-\s]*d[eé]l[eé]?g?\.?|"
     r"administrateur[s]?[- ]directeur[s]?", "administrateur_delegue"),
    (r"directeur[s]?\s+g[eé]n[eé]ra(?:l|ux)|direct(?:eurs?)?\.?\s*g[eé]n\.?|"
     r"dir\.?\s*g[eé]n\.?|directrice\s+g[eé]n[eé]rale",
     "directeur_general"),
    (r"commissaire[s]?\s+(?:aux\s+comptes|des\s+comptes)|commiss\.?\s+aux\s+comptes|"
     r"commissaire[s]?\s+suppl[eé]ant[s]?", "commissaire_aux_comptes"),
    (r"censeur[s]?", "censeur"),
    (r"administrateur[s]?\b|admin\.?\b|membre[s]?\s+du\s+conseil", "administrateur"),
    (r"directeur[s]?\b|directrice[s]?\b|dir\.?\b", "directeur"),
    (r"g[eé]rant[s]?\b|g[eé]rance", "gerant"),
    (r"secr[eé]taire[s]?(?:\s+g[eé]n[eé]ral)?", "secretaire"),
    (r"liquidateur[s]?", "liquidateur"),
    (r"fondateur[s]?|souscripteur[s]?", "fondateur"),
    (r"ing[eé]nieur[s]?[- ]conseil", "ingenieur_conseil"),
]
ROLE_RES = [(re.compile(p, re.I), canon) for p, canon in ROLE_RULES]


def canonical_role(text: str) -> str:
    t = clean_text(text)
    if not t:
        return ""
    for rx, canon in ROLE_RES:
        if rx.search(t):
            return canon
    return ""


# --- board list triggers -------------------------------------------------
# Each trigger names the default role for members listed without one.
#
# Triggers must be anchored on an explicit list marker: a heading in capitals,
# a directory field label ("Conseil. -"), or a phrase that announces a list
# ("est compose de", "sont :"). A bare case-insensitive "conseil
# d'administration" is deliberately NOT a trigger: the phrase occurs constantly
# in narrative prose ("le conseil d'administration est autorise a emettre des
# obligations"), and treating it as one turns paragraphs into fictitious names.
TRIGGERS: list[tuple[re.Pattern, str, str]] = [
    # Capitalised heading only - case-sensitive on purpose.
    (re.compile(r"CONSEIL\s+D['’]ADMINISTRATION\s*:?"), "administrateur", "conseil_heading"),
    (re.compile(r"CONSEIL\s+DE\s+SURVEILLANCE\s*:?"), "conseil_surveillance", "conseil_surv_heading"),
    (re.compile(r"\bConseil\s+de\s+surveillance\s*[:—–]"), "conseil_surveillance", "conseil_surv"),
    (re.compile(r"\bConseil\s*\.\s*[—–-]"), "administrateur", "conseil_annuaire"),
    (re.compile(r"\bConseil\s*:"), "administrateur", "conseil_colon"),
    (
        re.compile(
            r"\b(?:membres\s+du\s+)?conseil\s+d['’]administration\s*"
            r"(?:est\s+(?:ainsi\s+)?compos[eé]e?\s+(?:de|comme\s+suit)|"
            r"compos[eé]e?\s+de|se\s+compose\s+de|est\s+form[eé]\s+de|"
            r"comprend\s*:|\s*:)",
            re.I,
        ),
        "administrateur",
        "conseil_compose",
    ),
    (
        re.compile(
            r"\b(?:nomme|nomm[eé]s?|[eé]lus?)\s+(?:membres?\s+du\s+)?conseil"
            r"\s+d['’]administration\s*:",
            re.I,
        ),
        "administrateur",
        "conseil_nomme",
    ),
    (
        re.compile(r"\bLes\s+premiers\s+administrateurs\s+(?:sont|seront)\s*:?", re.I),
        "administrateur",
        "premiers_admin",
    ),
    (re.compile(r"\bAdministrateurs?\s*\.?\s*[:—–]"), "administrateur", "admin_label"),
    (
        re.compile(r"\bCommissaires?\s+(?:aux|des)\s+comptes\s*\.?\s*[:—–]", re.I),
        "commissaire_aux_comptes",
        "commissaires",
    ),
    (re.compile(r"\bDirecteurs?\s+g[eé]n[eé]ra(?:l|ux)\s*\.?\s*[:—–,]"), "directeur_general", "dg"),
    (re.compile(r"\bDirection\s*\.?\s*[:—–]"), "directeur", "direction"),
    (re.compile(r"\bG[eé]rants?\s*\.?\s*[:—–]"), "gerant", "gerants"),
    (re.compile(r"\bCenseurs?\s*\.?\s*[:—–]"), "censeur", "censeurs"),
    # Abbreviated register of the Annuaire industriel:
    #   "Cons. d'adm. Pres. : M. Louis Godart, 15, r. Vavin ; Adm. : MM. ..."
    (re.compile(r"\bCons\.\s*d['’]\s*adm\.\s*:?"), "administrateur", "cons_adm_abbrev"),
    (re.compile(r"\bPr[eé]s\.\s*:"), "president", "pres_abbrev"),
    (re.compile(r"\bVice-?pr[eé]s\.\s*:"), "vice_president", "vice_pres_abbrev"),
    (re.compile(r"\bAdm\.\s*(?:-\s*d[eé]l\.)?\s*:"), "administrateur", "adm_abbrev"),
    (re.compile(r"\bComm?\.\s*aux\s*comptes\s*:?", re.I), "commissaire_aux_comptes", "comm_abbrev"),
    (re.compile(r"\bDir\.\s*(?:g[eé]n\.)?\s*:"), "directeur", "dir_abbrev"),
]

# Field labels used by the directories; they terminate a board list.
FIELD_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:Capital|Objet|Exp|Agences|Succursales|Bilan|Dividendes|Si[eè]ge|"
    r"T[eé]l|T[eé]l[eé]gr|R\.\s?C|Notes?|Observations?|Production|Usines?|Actif|Passif|"
    r"Exercice|Assembl[eé]e|Statuts|Portefeuille|Participations?|Filiales?)\s*\.?\s*[:—–]",
    re.I,
)
SEPARATOR_RE = re.compile(r"[—–\-_=]{4,}|\n\s*\n")


# --- anchors -------------------------------------------------------------
MONTH_ALT = (
    r"janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|"
    r"octobre|novembre|d[eé]cembre"
)
# A dated press citation: "(La Journee industrielle, 22 mars 1927)",
# "(Exposition coloniale internationale de Paris, 1931)".
#
# The date structure is required, not merely a comma and a four-digit number.
# Matching any parenthesis containing a year swept up company-history notes -
# "(Anciens Ets Salmon, fondes en 1818)", "(Ancienne maison P. Lemoine, fondee
# en 1867)" - and then carried 1818 forward as the observation year for every
# board that followed, producing 150-year careers.
CITATION_RE = re.compile(
    rf"\(\s*(?P<body>[^()\n]{{3,70}}?,\s*"
    rf"(?:(?:\d{{1,2}}(?:er)?\s+)?(?:{MONTH_ALT})(?:\s*[-–]\s*(?:{MONTH_ALT}))?\s+)?"
    rf"(?P<year>{YEAR})(?:\s*[-–]\s*(?:{YEAR}))?"
    rf"(?:\s*,\s*(?:p+\.?|nos?\.?)\s*[\d\-–\s]+)?)\s*\)",
    re.I,
)
# Even with the date structure required, a parenthesis that narrates the firm's
# origins is a history note rather than a source.
HISTORY_NOTE_RE = re.compile(
    r"\b(?:fond[eé]e?s?|ancienne?s?|anct|cr[eé][eé]e?s?|constitu[eé]e?s?|"
    r"a\s+pris\s+la\s+suite|remonte|origine|depuis|absorb[eé]e?|reprise?)\b",
    re.I,
)
# Inline directory entry: "AEC 1922-519 - Ste generale des abattoirs ...".
# The page number is written three ways: "AEC 1922-519 - Name",
# "AEC 1922. - 489 - Name" and "AEC 1922. 495 - Name". Only the first matched,
# so 17 entries across 11 documents never anchored and their boards fell to
# whichever firm was in scope.
AEC_RE = re.compile(
    rf"\bAEC\s*(?P<year>{YEAR})\s*\.?\s*(?:[-–—]\s*)?(?P<page>\d{{1,4}})\s*[-–—]\s*"
    rf"(?P<name>[^\n]{{3,140}})"
)
# Once an AEC listing is running, the compiler stops repeating the prefix and
# gives the page alone: "509 - Sté des briqueteries de Fedhala". Unanchored,
# those entries' boards went to whichever firm was still in scope.
#
# Three digits, or an explicit "[= NNN]" correction. The annuaire runs to
# 800-1,200 pages, so a real reference is three digits; the one- and two-digit
# matches are enumerated clauses in legal prose - "3 - Modifications diverses
# aux articles 4, 8...", "5 - Que l'imprimeur a estimé que...". Requiring three
# digits took a hand-checked sample from 44 matches at roughly 60% precision to
# 19 at 19 of 19. An en/em dash only, and on the same line as the number: a
# hyphen makes "1877-Démissionnaire le 16 mai" and a life date look like an
# entry.
AEC_BARE_PAGE_RE = re.compile(
    r"(?m)^(?:\d{3}|\d{1,3}[ ]*\[=[ ]*\d{1,4}[ ]*\])[ ]*[–—][ ]*"
    r"(?P<name>[A-ZÉÈÀÂÎÔÛÇ«\"][^\n]{3,90})"
)
# "Annuaire Desfosses, 1945, p. 765 : Societe africaine de mines"
DESFOSSES_RE = re.compile(
    rf"\bAnnuaire\s+(?P<pub>Desfoss[eé]s|des\s+valeurs[^,\n]{{0,40}}|industriel[^,\n]{{0,30}}|"
    rf"g[eé]n[eé]ral[^,\n]{{0,30}})\s*,?\s*(?P<year>{YEAR})(?:\s*[-–]\s*{YEAR})?"
    rf"(?:\s*,\s*p\.?\s*(?P<page>[\d\-]+))?\s*:?\s*(?P<name>[^\n]{{0,140}})"
)
# Directory header: "ANNUAIRE DES ENTREPRISES COLONIALES, 1937".
ANNUAIRE_HEADER_RE = re.compile(
    rf"ANNUAIRE\s+DES\s+ENTREPRISES\s+COLONIALES\s*,?\s*(?P<year>{YEAR})", re.I
)
# Numbered directory entry at the start of a line: "89 - Banque commerciale du
# Maroc,". Entry numbers may be suffixed: "857 bis - U...".
NUMBERED_ENTRY_RE = re.compile(
    r"(?:^|\n)\s{0,4}(?P<num>\d{1,4}(?:\s*(?:bis|ter|quater))?)\s*[—–]\s*"
    r"(?P<name>[A-ZÉÈÀÂÎÔÛÇ«\"'][^\n]{3,140})",
    re.I,
)
# The "local companies" register used in the second part of some directories:
#   "Les Cultures marocaines, 43, rue ... - Societe an., f. le 1er juillet 1929,
#    1 million de fr. - ... - Conseil : MM. Eugene Garanger, ..."
# The entry opens at a line start with the firm's name, then its address, then
# an em-dash-separated run of fields.
DASH_ENTRY_RE = re.compile(
    r"(?:^|\n)(?P<name>[A-ZÉÈÀÂÎÔÛÇ«\"'][^\n—–]{3,90}?),\s*"
    r"(?:\d+\s*(?:bis|ter)?\s*,?\s*)?"
    r"(?:rue|r\.|avenue|av\.|boulevard|bd|bld|place|pl\.|quai|chemin|route|villa|"
    r"immeuble|imm\.|angle|zone|km|B\.?\s?P\.?)[^\n]{0,90}?[—–]\s",
    re.I,
)
# Annuaire industriel entry: the firm's name in capitals at the start of a line,
# followed by the inverted generic head in parentheses:
#   "ABATTOIRS MUNICIPAUX ET INDUSTRIELS AU MAROC (Soc. gen. des), siege adm. :"
# Anchored with (?m)^ rather than (?:^|\n) so that `m.start()` is the first
# character of the line, not the newline before it. With the old form this
# pattern reported a position one character earlier than
# ANNUAIRE_INDUS_ENTRY_RE for the same notice head, so the two never collided
# and the anchor de-duplication below silently did nothing: 357 head pairs
# differed by exactly one character.
CAPS_ENTRY_RE = re.compile(
    r"(?m)^(?P<name>[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ0-9\s'’&.\-«»]{5,90}?)\s*"
    r"\((?P<head>[^)\n]{2,60})\)"
)

# The *Annuaire industriel* proper. Its notices are alphabetised on a keyword,
# so the head is inverted and the rest of the legal name sits in parentheses:
#
#     ALLUMETTES (Soc. indo-chinoise forestiere et des), 41, bd de Magenta...
#     BANQUE de l'INDOCHINE, 96, bd Haussmann, Paris, 8e. ...
#
# Both are notice heads; only the first has a parenthetical. CAPS_ENTRY_RE
# requires one, so "BANQUE de l'INDOCHINE" did not anchor and its board was
# credited to the previous notice - which is how one firm-year came to hold 83
# directors. Here the parenthetical is optional and the address comma (or the
# period of "(Societe). 53, cours...") terminates the head.
#
# The lowercase connectors have to be inside the keyword: the annuaire prints
# "ETAINS et WOLFRAM du TONKIN" as one alphabetised keyword, and cutting at the
# first lowercase word would name the firm "Etains".
# The keyword is a run of capitalised words, and three things join them:
#
#   a particle chain   "BANQUE de l'INDOCHINE"     two particles, not one
#   a plain space      "CULTURES TROPICALES"
#   a comma           "FORGES, ATELIERS et CHANTIERS d'INDOCHINE"
#
# All three had to be handled before the head could be read whole. Requiring a
# capital straight after "de" left the first unanchored; treating the comma as
# the head's terminator named the third firm "Forges".
#
# The comma is only a separator when an ALL-CAPS word follows it. The address
# comma is followed by a street number or a mixed-case word - ", Bureau : 119,
# bd Haussmann" - so the run stops there on its own. Every separator is a
# literal space class rather than \s, which keeps a head from crossing a
# newline into the next notice.
_INDUS_CAP = r"[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ0-9'’\-]{1,}"
_INDUS_PARTICLE = r"(?:de|du|des|d[’']|l[’']|le|la|les|au|aux|en|sur|et|[àa])"
_INDUS_SEP = rf"(?:[ ]+{_INDUS_PARTICLE}(?:[ ]+{_INDUS_PARTICLE})*[ ]*|[ ]*,[ ]*|[ ]+)"
ANNUAIRE_INDUS_ENTRY_RE = re.compile(
    rf"(?m)^(?P<kw>{_INDUS_CAP}(?:{_INDUS_SEP}{_INDUS_CAP})*)"
    rf"(?:[ ]*\((?P<paren>[^)\n]{{2,110}})\))?[ ]*[,.]"
)
# Every notice ends with the publisher's internal classification number, which
# the annuaire itself explains: "Les chiffres entre parentheses a la fin de
# chaque notice servent a notre classement interieur". It is the one entry
# boundary this genre states outright, so it is used to detect the genre.
ANNUAIRE_INDUS_TERM_RE = re.compile(r"\(\d{1,2}-\d{4,6}\)")
MIN_INDUS_TERMINATORS = 5
APOSTROPHES = ("'", "’")


def annuaire_indus_name(kw: str, paren: str | None) -> str:
    """Undo the annuaire's alphabetisation inversion.

    "ALLUMETTES (Soc. indo-chinoise forestiere et des)" is the notice for the
    *Societe indo-chinoise forestiere et des allumettes*: the parenthetical is
    the head of the name and the capitalised keyword is its tail. Joining them
    in that order recovers a name that resolves against the company list; the
    printed order does not.

    Casing is left as printed. The keyword is upper-case because the annuaire
    alphabetises on it, and lowering it correctly needs to know which tokens
    are proper nouns - "COTONNIERE de TOLGA" is a descriptor plus a place.
    Since `org_key` folds case anyway, a wrong guess would cost display quality
    for no matching gain, so no guess is made.
    """
    kw = clean_text(kw).strip(" ,.;:")
    if not paren:
        return kw
    paren = clean_text(paren).strip(" ,.;:")
    joiner = "" if paren.endswith(APOSTROPHES) else " "
    return f"{paren}{joiner}{kw}"

# Field labels that must never be mistaken for a company name by an anchor.
ANCHOR_NOT_A_NAME_RE = re.compile(
    r"^(?:capital|objet|conseil|cons\b|si[eè]ge|t[eé]l|t[eé]l[eé]gr|exp\b|agences|"
    r"succursales|bilan|dividendes|statuts|production|observations?|actif|passif|"
    r"exercice|assembl[eé]e|portefeuille|participations?|filiales?|notes?|"
    r"administrateurs?|adm\b|pr[eé]s\b|directeurs?|dir\b|commissaires?|"
    r"bureaux?|adresse|mandataire|repr[eé]sentants?|agents?|correspondants?|"
    r"si[eè]ges?|t[eé]l[eé]phone|domicile|usine|magasins?|entrep[oô]ts?|"
    r"suite|fin|voir|cf|in\b|pp\b)",
    re.I,
)
# Articles are not rejected as prefixes - "La Manutention marocaine" and
# "L'Alfa" are real company names - only when they are the whole string.
ANCHOR_STOPWORD_ONLY_RE = re.compile(
    r"^(?:le|la|les|l['’]|de|du|des|et|en|au|aux|the|of|p|pp)\.?$", re.I
)
# Address-like tail that follows a company name in a directory entry.
NAME_TAIL_SPLIT_RE = re.compile(
    r"\s*[,.]\s*(?=(?:si[eè]ge|bureaux?|adresse|\d|T\.\s|T[eé]l|R\.\s?C|bd\b|bld\b|"
    r"r\.|av\.|pl\.|rue|avenue|boulevard|place|quai|chemin|route|villa|imm))",
    re.I,
)


def clean_anchor_company(raw: str) -> str:
    """Validate and tidy a company name captured by an anchor.

    Anchor regexes read to end of line, so they pick up the address and
    telephone number that follow the name, and sometimes fire on a field label
    instead of a name. An invalid capture must return "" so that the caller
    keeps the company already in scope rather than losing attribution.
    """
    n = clean_text(raw)
    if not n:
        return ""
    n = NAME_TAIL_SPLIT_RE.split(n, maxsplit=1)[0]
    n = re.sub(r"\s*[:;]\s*.*$", "", n)
    # Editorial brackets leak into names: "Bongola-Lokundji [sic".
    n = re.sub(r"\s*\[.*$", "", n)
    # A renaming records two firms; keep the first as the display name. The
    # matching key drops the tail too (see names.PREDECESSOR_TAIL_RE).
    n = re.sub(r"\s*,?\s*\b(?:puis|devenue?|renomm[eé]e?)\b.*$", "", n, flags=re.I)
    n = n.strip(" .,;:—–-*")
    if len(n) < 4 or len(re.findall(r"[A-Za-zÀ-ÿ]", n)) < 3:
        return ""
    if not re.match(r"^[A-ZÉÈÀÂÎÔÛÇ«\"'0-9]", n):
        return ""
    if ANCHOR_NOT_A_NAME_RE.match(n) or ANCHOR_STOPWORD_ONLY_RE.match(n):
        return ""
    # A balance-sheet caption or a periodical title is not a firm. Both sit
    # close to boards in the text and otherwise become company nodes.
    if ACCOUNTING_RE.match(n) or PUBLICATION_RE.search(n):
        return ""
    # Un-invert "X (Societe des)" into "Societe des X", as in the catalogue.
    from common import split_title

    parsed = split_title(n)
    name = parsed["name_normalised"] or n
    # A bare city is an address line, not an entry heading: directory addresses
    # end "..., PARIS (9e)", which looks exactly like a capitalised entry.
    if strip_accents(name).lower().strip(" .") in PLACES:
        return ""
    return name
# Internal cross-reference to another document on the site.
XREF_RE = re.compile(r"(?:https?://)?(?:www\.)?entreprises-coloniales\.fr/(?P<path>[^\s)\]]+\.pdf)", re.I)

# Company attribute observations.
CAPITAL_RE = re.compile(
    r"capital(?:\s+social)?(?:\s+(?:de|est\s+de|port[eé]\s+[aà]|fix[eé]\s+[aà]))?\s*:?\s*"
    r"(?P<amount>\d[\d .,]{2,20})\s*(?P<unit>millions?|milliards?|MF)?\s*(?:de\s+)?"
    r"(?P<currency>francs?|fr\.?|piastres?|\$)",
    re.I,
)
FOUNDED_RE = re.compile(
    rf"(?:soci[eé]t[eé]\s+an(?:onyme|\.)?[^.\n]{{0,40}}?)?"
    rf"(?:fond[eé]e?|constitu[eé]e?|cr[eé][eé]e?|f\.)\s+le\s+"
    rf"(?P<day>\d{{1,2}})(?:er)?\s+(?P<month>[a-zéûôA-Z]{{3,12}})\s+(?P<year>{YEAR})",
    re.I,
)
SIEGE_RE = re.compile(
    r"si[eè]ge\s+(?:social|administratif|d['’]exploitation)?\s*:?\s*(?:[aà]\s+)?(?P<addr>[^\n;]{4,120})",
    re.I,
)

MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12, "décembre": 12,
}

MAX_LIST_CHARS = 1600
# Maximum distance a directory-entry company stays in scope. Chosen from the
# observed length of directory entries (a few hundred to ~2,000 characters);
# beyond it, attribution is dropped rather than risked.
MAX_ENTRY_SCOPE = 6000


# --- segmentation --------------------------------------------------------
class Anchor:
    __slots__ = ("pos", "kind", "year", "source", "company", "page")

    def __init__(self, pos, kind, year="", source="", company="", page=""):
        self.pos = pos
        self.kind = kind
        self.year = year
        self.source = source
        self.company = company
        self.page = page


# Which anchor wins when two match the same position. Lower is stronger. A
# dated source beats an undated entry head, and a genre-specific entry pattern
# beats the generic capitals one.
ANCHOR_PRECEDENCE = {
    "citation": 0,
    "aec_entry": 1,
    "directory_entry": 2,
    "annuaire_header": 3,
    "numbered_entry": 4,
    "annuaire_industriel_entry": 5,
    "caps_entry": 6,
    "dash_entry": 7,
}


def is_annuaire_industriel(text: str) -> bool:
    """True for the *Annuaire industriel* genre, by its own entry terminator."""
    return len(ANNUAIRE_INDUS_TERM_RE.findall(text)) >= MIN_INDUS_TERMINATORS


def find_anchors(text: str, is_annuaire: bool) -> list[Anchor]:
    anchors: list[Anchor] = []
    industriel = is_annuaire_industriel(text)

    for m in ANNUAIRE_HEADER_RE.finditer(text):
        anchors.append(Anchor(m.start(), "annuaire_header", m.group("year"),
                              "Annuaire des entreprises coloniales"))
    aec_years: list[tuple[int, str]] = []
    for m in AEC_RE.finditer(text):
        aec_years.append((m.start(), m.group("year")))
        anchors.append(Anchor(m.start(), "aec_entry", m.group("year"),
                              f"AEC {m.group('year')}, p. {m.group('page')}",
                              clean_anchor_company(m.group("name")), m.group("page")))
    if aec_years:
        # A bare page belongs to the listing it sits in, so it takes the year of
        # the nearest AEC entry *before* it, not the document's first. The
        # Fedhala dossier reprints AEC 1922 and then AEC 1951; taking the first
        # stamped the two 1951 entries (pages 826 and 857 - only a volume that
        # long has them) as 1922, a 29-year error on four board seats.
        for m in AEC_BARE_PAGE_RE.finditer(text):
            name = clean_anchor_company(m.group("name"))
            if not name:
                continue
            year = next((y for pos, y in reversed(aec_years) if pos < m.start()),
                        aec_years[0][1])
            anchors.append(Anchor(m.start(), "aec_entry", year, f"AEC {year}", name))
    for m in DESFOSSES_RE.finditer(text):
        pub = clean_text(m.group("pub"))
        anchors.append(Anchor(m.start(), "directory_entry", m.group("year"),
                              f"Annuaire {pub} {m.group('year')}",
                              clean_anchor_company(m.group("name") or ""), m.group("page") or ""))
    for m in CITATION_RE.finditer(text):
        body = clean_text(m.group("body"))
        if HISTORY_NOTE_RE.search(body):
            continue
        anchors.append(Anchor(m.start(), "citation", m.group("year"), body))
    if is_annuaire:
        for m in NUMBERED_ENTRY_RE.finditer(text):
            anchors.append(Anchor(m.start(), "numbered_entry", "", "",
                                  clean_anchor_company(m.group("name")), m.group("num")))
    if industriel:
        # This genre's own head pattern, which segments where CAPS_ENTRY_RE
        # cannot. Registered before it so that on a tie the more specific
        # anchor wins the position.
        for m in ANNUAIRE_INDUS_ENTRY_RE.finditer(text):
            name = clean_anchor_company(
                annuaire_indus_name(m.group("kw"), m.group("paren")))
            if name:
                anchors.append(Anchor(m.start(), "annuaire_industriel_entry",
                                      "", "", name))
    if is_annuaire:
        # Annuaire industriel style: name in capitals, generic head in parens.
        for m in CAPS_ENTRY_RE.finditer(text):
            head = clean_text(m.group("head"))
            # "(9e)" is a Paris arrondissement in an address, not a generic head.
            if re.fullmatch(r"\d{1,2}\s*e(?:r|me)?|[A-Z]{2,3}", head):
                continue
            name = clean_anchor_company(f"{m.group('name')} ({head})")
            if name:
                anchors.append(Anchor(m.start(), "caps_entry", "", "", name))
        # "Local companies" register: name, address, then dash-separated fields.
        for m in DASH_ENTRY_RE.finditer(text):
            name = clean_anchor_company(m.group("name"))
            if name:
                anchors.append(Anchor(m.start(), "dash_entry", "", "", name))

    # Two patterns can match the same notice head - CAPS_ENTRY_RE and this
    # genre's own. Keeping both would insert a zero-length segment and let the
    # weaker name win, so one anchor per position, most specific first.
    anchors.sort(key=lambda a: (a.pos, ANCHOR_PRECEDENCE.get(a.kind, 99)))
    deduped: list[Anchor] = []
    for a in anchors:
        if deduped and deduped[-1].pos == a.pos:
            continue
        deduped.append(a)
    return deduped


# Anchors that introduce a *structured* directory entry. Inside a single-firm
# dossier these are that firm's own entry, so an unparseable entry name can
# safely fall back to the dossier's company. A `citation` is not on this list:
# a press extract inside a dossier may be about anyone, and one sampled case
# was a concession application by a man who sat on no board at all.
DOSSIER_FALLBACK_KINDS = {"directory_entry", "aec_entry", "numbered_entry",
                          "annuaire_header"}


def build_segments(text: str, is_annuaire: bool, default_company: str,
                   dossier_fallback: bool = False) -> list[dict]:
    """Split a document into dated, company-attributed segments.

    `dossier_fallback` recovers attribution in a single-firm dossier. The
    anchor rules below deliberately blank the company when a directory entry's
    name cannot be validated, because in a multi-firm annuaire keeping the
    previous firm credits it with the next firm's board. But in a dossier
    *about one firm*, that same blanking discards ties whose owner is known
    from the catalogue title - 7,729 of them. The caller passes True only for
    a company dossier that is not itself an annuaire.
    """
    anchors = find_anchors(text, is_annuaire)
    segments: list[dict] = []

    # State carried forward: the last explicit year and company seen.
    cur_year = ""
    cur_company = default_company
    cur_source = ""

    if not anchors:
        return [
            {
                "start": 0,
                "text": text,
                "year": "",
                "source": "",
                "company": default_company,
                "anchor": "none",
            }
        ]

    if anchors[0].pos > 0:
        segments.append(
            {
                "start": 0,
                "text": text[: anchors[0].pos],
                "year": "",
                "source": "",
                "company": default_company,
                "anchor": "preamble",
            }
        )

    entry_kinds = {"aec_entry", "numbered_entry", "directory_entry", "caps_entry",
                   "dash_entry", "annuaire_industriel_entry"}
    # Position of the entry anchor that put the current company in scope, and
    # whether the company came from an entry rather than from the document.
    entry_pos = -1
    from_entry = False

    for i, a in enumerate(anchors):
        end = anchors[i + 1].pos if i + 1 < len(anchors) else len(text)
        year = plausible_year(a.year)
        if year:
            cur_year = year
        if a.source:
            cur_source = a.source
        if a.kind in entry_kinds:
            # A directory entry *replaces* the company in scope, even when its
            # name could not be validated. Keeping the previous one would
            # silently attribute this entry's board to the firm listed above it,
            # which is worse than leaving the tie unattributed.
            cur_company = a.company
            entry_pos = a.pos
            from_entry = True
        elif a.kind == "annuaire_header":
            cur_company = default_company
            from_entry = False

        company = cur_company
        # Safeguard: a directory entry describes one firm over a few hundred to
        # a couple of thousand characters. If the company in scope came from an
        # entry that is now far behind, the document has moved into a register
        # the anchors do not recognise, so drop attribution rather than credit
        # a long run of other firms' boards to this one.
        if from_entry and entry_pos >= 0 and a.pos - entry_pos > MAX_ENTRY_SCOPE:
            company = ""

        attribution = "anchor" if company else ""
        if not company and dossier_fallback and a.kind in DOSSIER_FALLBACK_KINDS:
            company = default_company
            attribution = "dossier_fallback"

        segments.append(
            {
                "start": a.pos,
                "text": text[a.pos : end],
                "year": cur_year,
                "source": cur_source,
                "company": company,
                "anchor": a.kind,
                "attribution": attribution,
                "page": a.page,
            }
        )
    return segments


# --- board list parsing --------------------------------------------------
# A sentence in flowing prose, rather than a list entry. Any of these as the
# first word of a fragment means the trigger caught narrative text.
PROSE_START_RE = re.compile(
    r"^(?:le|la|les|un|une|des|du|de|d'|qui|que|qu'|dont|est|sont|a|ont|au|aux|en|"
    r"dans|pour|par|avec|sans|sur|sous|cette|ce|ces|cet|il|elle|ils|elles|on|"
    r"nous|vous|leur|leurs|son|sa|ses|notre|votre|mais|or|donc|car|ainsi|puis|"
    r"apr[eè]s|avant|lors|depuis|pendant|afin|comme|si|tout|tous|toute|toutes|"
    r"aucun|plusieurs|chaque|m[eê]me|autre|autres|ledit|ladite|susdit)\b",
    re.I,
)
# Verb forms that betray a sentence rather than a name list.
PROSE_VERB_RE = re.compile(
    r"\b(?:est|sont|a\s+[eé]t[eé]|ont\s+[eé]t[eé]|sera|seront|avait|avaient|"
    r"poss[eè]de|d[eé]cid[eé]|autoris[eé]|nomm[eé]|constitu[eé]|"
    r"s'[eé]l[eè]ve|comprend|figure|permet|doit|peut|vient)\b",
    re.I,
)


# Field labels, balance-sheet prose and addresses that survive name parsing
# and become "people". These were always in the data but sat harmlessly
# unattributed; recovering attribution (see build_segments) would promote them
# into real edges, so they are dropped outright - which also removes 3,209
# that were already attributed before that change.
# A role label the list parser swallowed, ahead of the name it introduces. The
# label is captured, not just removed: it states the role of the name behind it,
# and the enclosing list's role is usually a different one. Discarding it filed
# 199 "Adm.:" rows as `president` and 113 "Prés.:" rows as `administrateur`.
#
# The separators are all loose because the sources abbreviate inconsistently:
# "Prés:. M. J. Garcin" puts the period on the wrong side of the colon,
# "Adm.-dél.:" hyphenates where "adm. dél." spaces, and "direct. gén.:" splits
# a two-word title across an abbreviation point.
_LABEL_SEP = r"[-.\s]*"
MEMBER_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?P<label>"
    r"v(?:ice)?" + _LABEL_SEP + r"pr[ée]s(?:id)?(?:ent)?e?s?|"
    r"adm(?:in)?(?:istrateurs?)?\.?" + _LABEL_SEP +
    r"(?:d[ée]l[ée]gu[ée]e?s?|dél\.?|dels?)|"
    r"adm(?:in)?(?:istrateurs?)?|"
    r"pr[ée]s(?:id)?(?:ent)?e?s?|"
    r"direct(?:eurs?|rices?)?\.?" + _LABEL_SEP + r"g[ée]n(?:[ée]ral)?e?s?|"
    r"direct(?:eurs?|rices?)?|dir|d\.?\s*g|"
    r"g[ée]rants?|censeurs?|secr[ée]taires?|"
    r"commissaires?(?:" + _LABEL_SEP + r"aux" + _LABEL_SEP + r"comptes)?|"
    r"fond[ée]s?\s+de\s+pouvoirs?|repr[ée]sentants?|mandataires?"
    r")\s*\.?\s*:\s*\.?\s*", re.I)
MEMBER_JUNK_RE = re.compile(
    r"\b(capital|commissaires?|propri[ée]taires?|si[èe]ge|statuts|exercice|"
    r"dividende|assembl[ée]e|bilan|r[ée]serves?|archives|galeries|"
    r"nomm[ée]s?\s+pour|pris\s+parmi|n[ée]\s+[àa]\s|fr[èe]re\s+d|"
    r"conseil|administration|exp\.)", re.I)
MEMBER_ADDRESS_RE = re.compile(
    r",\s*(?:r\.|bd|av\.|rue|boulevard|avenue|place|quai)\s|\bparc\s+de\b", re.I)
# A period after a word of four or more letters, then a capital: a swallowed
# sentence boundary. Four letters, because "Ed. Bousquet" and "F. Urruty" are
# ordinary names and a shorter rule flags 22,560 of them.
MEMBER_SENTENCE_RE = re.compile(r"[^\W\d_]{4,}\.\s+[A-ZÉÈÀÂÎÔÛÇ]")


def member_is_junk(name: str) -> bool:
    """True when a parsed 'person' is really a field label, an address or prose."""
    if not name:
        return True
    return bool(MEMBER_JUNK_RE.search(name)
                or MEMBER_ADDRESS_RE.search(name)
                or MEMBER_SENTENCE_RE.search(name))


def _fragment_is_namelike(frag: str) -> bool:
    f = tidy_fragment(frag).strip(" .,;:")
    if not f or len(f) > 60:
        return False
    tokens = f.split()
    if not tokens or len(tokens) > 7:
        return False
    # PROSE_START_RE lists French function words, several of which are also the
    # opening of a perfectly good name: the verb "a" collides with the initial
    # in "A. R. Fontaine", and "d'", "le", "la", "du", "des" collide with the
    # particle surnames "D'Aubigny", "Le Bris", "Du Pasquier", "Des Rotours".
    # A fragment is therefore exempt when it opens like a name - an initial, or
    # a capitalised word followed by another capitalised word - since running
    # prose continues in lower case ("Les travaux comme...").
    opens_like_name = bool(
        re.match(r"^[A-ZÉÈÀÂÎÔÛÇ]\.", f)
        or re.match(r"^[A-ZÉÈÀÂÎÔÛÇ][a-zéèêëàâîïôöûüùç]*['’]?\s*[A-ZÉÈÀÂÎÔÛÇ]", f)
    )
    if not opens_like_name and PROSE_START_RE.match(f) and not looks_like_org(f):
        return False
    # A full stop inside the fragment means a sentence boundary was swallowed,
    # unless it is an initial or a standard abbreviation ("A. R. Fontaine").
    if re.search(r"\.\s+[a-zéèêàâîôûç]", f):
        return False
    if len(re.findall(r"\d", f)) > 2:
        return False
    return bool(re.search(r"[A-ZÉÈÀÂÎÔÛÇ]", f))


def looks_like_name_list(body: str) -> bool:
    """Reject trigger matches that caught prose instead of a list of members."""
    b = tidy_fragment(body)
    if len(b) < 4:
        return False
    # "MM." / "Messieurs" is a decisive marker of a list of people.
    if re.match(r"^[:\s—–-]*(?:MM\.|Messieurs|M\.\s)", b):
        return True
    parts = [p.strip() for p in re.split(r"[;,]", b) if p.strip()]
    if len(parts) < 2:
        # A single member is legitimate ("Gerant : M. Dupont") but only if it is
        # short and name-shaped rather than a clause.
        return _fragment_is_namelike(b) and not PROSE_VERB_RE.search(b)
    namelike = sum(1 for p in parts if _fragment_is_namelike(p))
    if namelike < 2:
        return False
    return namelike >= 0.5 * len(parts)


def find_board_lists(segment_text: str) -> list[tuple[str, str, str]]:
    """Yield (list_text, default_role, trigger_name) for each board list found.

    Overlapping trigger matches are resolved by first-come: several triggers
    can describe the same list ("CONSEIL D'ADMINISTRATION" immediately followed
    by "Administrateurs :"), and counting it once per trigger would inflate
    every tie by its number of matching patterns.
    """
    candidates: list[tuple[int, int, str, str, str]] = []
    for rx, default_role, name in TRIGGERS:
        for m in rx.finditer(segment_text):
            start = m.end()
            tail = segment_text[start : start + MAX_LIST_CHARS]
            cut = len(tail)
            for term in (FIELD_LABEL_RE, SEPARATOR_RE):
                t = term.search(tail)
                if t and t.start() < cut:
                    cut = t.start()
            nxt = NUMBERED_ENTRY_RE.search(tail)
            if nxt and nxt.start() < cut:
                cut = nxt.start()
            body = tail[:cut].strip()
            if len(body) < 4 or not looks_like_name_list(body):
                continue
            candidates.append((m.start(), start + len(body), body, default_role, name))

    candidates.sort(key=lambda c: (c[0], -(c[1] - c[0])))
    claimed: list[tuple[int, int]] = []
    out: list[tuple[str, str, str]] = []
    for start, end, body, role, name in candidates:
        if any(s <= start < e for s, e in claimed):
            continue
        claimed.append((start, end))
        out.append((body, role, name))
    return out


NAME_SPLIT_RE = re.compile(r"\s*(?:,|\bet\b|&)\s*")
# Annotations: "(Distill. Indoch.)" and "[Credit foncier d'Algerie]".
ANNOT_RE = re.compile(r"\(([^()]{2,80})\)|\[([^\]]{2,80})\]")
# Street addresses and locations. Abbreviations ending in "." are matched in a
# separate alternation: a trailing \b after "r\." can never match, because the
# boundary between "." and the following space is not a word boundary.
ADDRESS_RE = re.compile(
    r"^\s*(?:\d+\s*(?:bis|ter)?\s*,?\s*)?"
    r"(?:(?:rue|avenue|boulevard|bld|bd|place|quai|chemin|route|impasse|villa|cit[eé]|"
    r"faubourg|fbg|all[eé]e|square|cours|passage|domaine|demeurant|domicili[eé]|"
    r"si[eè]ge|bureaux?|adresse|immeuble|lotissement|km)\b"
    r"|(?:r\.|av\.|pl\.|bd\.|bld\.|imm\.|B\.?\s?P\.?|t[eé]l[eé]?gr?\.)"
    r"|[aà]\s)",
    re.I,
)
# French commune names of the "X-sur-Y" family are places, not people.
COMMUNE_RE = re.compile(r"-(?:sur|sous|l[eèa]s|les|en|le|la|du|de|aux?)-", re.I)
STOP_FRAGMENT_RE = re.compile(
    r"^(?:etc|idem|id|ibid|et\s+al|ainsi\s+que|ci-dessus|ci-dessous|susnomm[eé]s?|"
    r"les\s+m[eê]mes|non\s+d[eé]sign[eé]s?|inconnus?|divers|autres|suite|fin|"
    r"\?+|\.+|-+|n[eé]ant)\.?$",
    re.I,
)
# Legal-form and boilerplate fragments that are not entity names.
LEGAL_FRAGMENT_RE = re.compile(
    r"^(?:st[eé]|soci[eé]t[eé]|s)\.?\s*(?:an(?:on)?\.?|anonyme|civ(?:ile)?\.?|"
    r"[aà]\s*r\.?\s*l\.?|en\s+commandite|coop[eé]rative)?\.?$",
    re.I,
)
# Sector or object-clause words that leak in from adjacent directory fields.
GENERIC_FRAGMENT_RE = re.compile(
    r"^(?:achat|vente|commerce|industrie|travaux\s+publics?|transports?|importation|"
    r"exportation|agriculture|[eé]levage|banque|assurances?|immobilier|mines?|"
    r"exploitation|fabrication|production|repr[eé]sentation|imp|impr|imprimerie|"
    r"capital|objet|si[eè]ge|actions?|obligations?|dividendes?|exercice|bilan|"
    r"francs?|piastres?|total|divers|non)\.?$",
    re.I,
)


def parse_board_list(body: str, default_role: str) -> list[dict]:
    """Parse a board list into member records.

    The register is: role-bearing groups separated by ';' or ' - ', each group
    being one or more comma-separated names followed by a role phrase, e.g.

        MM. Georges Despret, presid. ; Wladimir Archawski, admin.-del. ;
        Mathieu Angelini, Victor Berti, ... , administrateurs.
    """
    body = tidy_fragment(body)
    body = re.sub(r"^\s*[:—–-]\s*", "", body)
    members: list[dict] = []

    # Split into role groups. ';' is the primary separator; ' - ' introduces a
    # new labelled group ("- Directeurs generaux a Paris, M. Hippolyte Gauran").
    groups = re.split(r"\s*;\s*|\s+[—–]\s+", body)
    for group in groups:
        group = group.strip(" .,")
        if not group:
            continue

        # A group may carry its own leading role label: "Directeurs generaux a
        # Paris, M. Hippolyte Gauran".
        group_role = ""
        lead = re.match(r"^([A-Za-zÀ-ÿ\s.'’-]{3,45}?)\s*[:]\s*(.+)$", group)
        if lead and canonical_role(lead.group(1)):
            group_role = canonical_role(lead.group(1))
            group = lead.group(2)

        # Trailing role phrase applying to every name in the group. The comma
        # split has to protect annotations for the same reason the 'et' split
        # does, or a bracketed note containing a comma is torn in two.
        tail_role = ""
        guarded, restore_group = _protect_annotations(group)
        parts = [restore_group(p) for p in re.split(r"\s*,\s*", guarded) if p.strip()]
        if parts:
            last = parts[-1].strip(" .")
            cr = canonical_role(last)
            # Only treat the last part as a role if it is (almost) nothing but
            # the role phrase, otherwise "Combescot, administrateur de societes
            # a Paris" would strip a real name.
            if cr and len(last.split()) <= 4 and not re.search(r"\bde\s+soci[eé]t[eé]s\b", last, re.I):
                tail_role = cr
                parts = parts[:-1]

        role = group_role or tail_role or default_role

        # Re-join and split on name boundaries, keeping annotations attached.
        for raw in parts:
            for frag in _split_names(raw):
                rec = _make_member(frag, role)
                if rec:
                    members.append(rec)
    return members


def _protect_annotations(raw: str):
    """Replace bracketed spans with placeholders, and return a restorer.

    Annotations contain commas and the word "et" - "[Wm. H. Muller et Cie,
    Rotterdam]" holds both - so any split on either boundary cuts them in half.
    The near half keeps the name and a dangling "[", the far half is pure
    residue: 1,367 parsed "people" were fragments like "Rotterdam]" and
    "censeur Ste generale]".
    """
    holes: list[str] = []

    def stash(m):
        holes.append(m.group(0))
        return f"\x00{len(holes) - 1}\x00"

    def restore(s: str) -> str:
        return re.sub(r"\x00(\d+)\x00", lambda m: holes[int(m.group(1))], s)

    return ANNOT_RE.sub(stash, raw), restore


def _split_names(raw: str) -> list[str]:
    """Split a comma-part into individual names, respecting 'et' and brackets."""
    raw = raw.strip()
    if not raw:
        return []
    protected, restore = _protect_annotations(raw)
    pieces = re.split(r"\s+et\s+|\s*&\s*", protected)
    return [restore(p).strip() for p in pieces if restore(p).strip()]


def _make_member(frag: str, role: str) -> dict | None:
    # Strip any residual placeholder left by the annotation-protection pass.
    frag = re.sub(r"\x00\d*\x00?", "", frag).strip(" .,;:*·•")
    if not frag or len(frag) < 3:
        return None
    if STOP_FRAGMENT_RE.match(frag) or ADDRESS_RE.match(frag):
        return None

    # Fold in the forenames the compiler supplied, before annotations are read,
    # otherwise "[eorges]" is mistaken for an annotation and the forename is
    # destroyed. Both of his conventions: expansion in place ("G[eorges]
    # Hersent") and a whole forename ahead of the surname ("[Charles]
    # Michel-Cote").
    from names import EXPANDED_INITIAL_RE, expand_leading_forename

    frag = EXPANDED_INITIAL_RE.sub(r"\1\2", frag)
    frag = expand_leading_forename(frag)
    annotations = [clean_text(a or b) for a, b in ANNOT_RE.findall(frag)]
    bare = ANNOT_RE.sub(" ", frag)
    # A role label swallowed into the fragment: "Adm.: MM. Henri Girche",
    # "Direct.: M. Patrick O'Quin", "Fonde de pouvoirs: Marcel Penicaud". These
    # carry a real name behind the label, so the label is stripped rather than
    # the row discarded - 1,514 rows held a colon and every hand-checked one was
    # of this shape. LEADING_MM_RE then removes the "MM." the label left behind,
    # so this has to run first.
    #
    # The label also *overrides* the role inherited from the enclosing list. It
    # is the more specific statement: a "Prés.:" inside a run of administrateurs
    # names the president, and taking the run's role instead is simply wrong.
    label = MEMBER_LABEL_PREFIX_RE.match(bare)
    if label:
        # The separator swallows the abbreviation's period, and several role
        # rules need it - "pres." is the president, bare "pres" is the
        # preposition - so a failed lookup is retried with it restored.
        text = label.group("label")
        labelled = canonical_role(text) or canonical_role(text + ".")
        if labelled:
            role = labelled
        bare = bare[label.end():]
    bare = LEADING_MM_RE.sub("", bare).strip(" .,;:")
    bare = re.sub(r"\s+", " ", bare).strip(" .,;:")
    if not bare or len(bare) < 3:
        return None
    # A colon that survived the strip means a field label this rule does not
    # know, not a person: no name in the corpus contains one.
    if ":" in bare:
        return None

    # Surname-first register with a trailing annotation: "SAVON (Robert)(de
    # Savon freres)". Stripping parentheses would drop the forename into the
    # annotation, so fold the first one back in when it is a forename.
    if annotations and re.fullmatch(r"[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ'’\- ]{1,40}", bare):
        from common import _is_forename

        if _is_forename(annotations[0]):
            bare = f"{bare} ({annotations[0]})"
            annotations = annotations[1:]
    if not _fragment_is_namelike(bare):
        return None
    # Occupational descriptors sometimes survive as their own fragment.
    from names import DESCRIPTOR_RE

    if DESCRIPTOR_RE.match(bare):
        return None
    if LEGAL_FRAGMENT_RE.match(bare) or GENERIC_FRAGMENT_RE.match(bare):
        return None
    # Periodical titles are sources, not entities; accounting captions sit in
    # balance-sheet tables next to the board and look like short names.
    if PUBLICATION_RE.search(bare) or ACCOUNTING_RE.match(bare):
        return None
    # A bare place name is a location, not a board member.
    if strip_accents(bare).lower().strip(" .") in PLACES:
        return None
    if ADDRESS_RE.match(bare) or (len(bare.split()) == 1 and COMMUNE_RE.search(bare)):
        return None
    if not re.search(r"[A-ZÉÈÀÂÎÔÛÇ]", bare):
        return None
    # Reject fragments that are mostly digits (addresses, capital figures).
    if len(re.findall(r"\d", bare)) > len(bare) / 4:
        return None

    is_org = looks_like_org(bare)
    rec = {
        "member_raw": clean_text(frag),
        "member_type": "organisation" if is_org else "person",
        "role": role,
        "annotation": "; ".join(annotations),
    }
    if is_org:
        rec["name_clean"] = normalise_org_name(bare)
        rec["entity_key"] = org_key(bare)
        rec["given"] = ""
        rec["surname"] = ""
    else:
        p = parse_person_name(bare)
        if not p["surname"]:
            return None
        rec["name_clean"] = p["name_clean"]
        rec["entity_key"] = p["person_key"]
        rec["given"] = p["given"]
        rec["surname"] = p["surname"]
        rec["parse_note"] = p["parse_note"]
    if not rec["entity_key"]:
        return None
    return rec


# --- company attributes --------------------------------------------------
def parse_attributes(seg_text: str) -> list[tuple[str, str]]:
    out = []
    m = FOUNDED_RE.search(seg_text)
    if m:
        mo = MONTHS.get(strip_accents(m.group("month")).lower(), 0)
        y = plausible_year(m.group("year"))
        if y:
            iso = f"{y}-{mo:02d}-{int(m.group('day')):02d}" if mo else y
            out.append(("founded_date", iso))
    m = CAPITAL_RE.search(seg_text)
    if m:
        amount = m.group("amount").strip().rstrip(".,")
        unit = (m.group("unit") or "").lower()
        cur = clean_text(m.group("currency"))
        out.append(("capital", clean_text(f"{amount} {unit} {cur}")))
    m = SIEGE_RE.search(seg_text)
    if m:
        addr = clean_text(m.group("addr")).strip(" .,")
        if 4 <= len(addr) <= 120:
            out.append(("head_office", addr))
    return out


# --- driver --------------------------------------------------------------
def load_documents() -> dict[str, dict]:
    path = os.path.join(PROC_DIR, "documents.csv")
    with open(path, encoding="utf-8", newline="") as fh:
        return {r["doc_id"]: r for r in csv.DictReader(fh)}


def is_annuaire_doc(doc: dict, text_head: str) -> bool:
    hay = f"{doc['pdf_url']} {doc['title_raw']}"
    if re.search(r"\bAEC_|annuaire", hay, re.I):
        return True
    return bool(ANNUAIRE_HEADER_RE.search(text_head)) or len(
        NUMBERED_ENTRY_RE.findall(text_head)
    ) >= 3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--doc", action="append", default=[], help="parse only these doc_ids")
    ap.add_argument("--out-suffix", default="")
    args = ap.parse_args()

    ensure_dir(PROC_DIR)
    docs = load_documents()

    files = sorted(glob.glob(os.path.join(TEXT_DIR, "*.txt.gz")))
    if args.doc:
        wanted = set(args.doc)
        files = [f for f in files if os.path.basename(f)[:-7] in wanted]
    if args.limit:
        files = files[: args.limit]

    affiliations: list[dict] = []
    org_affiliations: list[dict] = []
    attributes: list[dict] = []
    references: list[dict] = []
    report: list[dict] = []

    company_names: dict[str, dict] = {}
    n_junk = 0
    person_records: dict[str, dict] = defaultdict(
        lambda: {"person_key": "", "names": set(), "surname": "", "given": set(), "n_ties": 0}
    )

    for i, path in enumerate(files, 1):
        doc_id = os.path.basename(path)[:-7]
        doc = docs.get(doc_id)
        if doc is None:
            continue
        try:
            text = gzip.open(path, "rt", encoding="utf-8").read()
        except OSError:
            continue
        text = text.replace("\x0c", "\n")

        annuaire = is_annuaire_doc(doc, text[:6000])
        default_company = doc["name_normalised"] or doc["name_listed"]
        # Some catalogue entries are reference works, not firms ("Recueil des
        # societes coloniales et maritimes"). Their dossier must not become a
        # company node; ties inside them count only where an entry anchor names
        # an actual firm.
        if PUBLICATION_RE.search(default_company):
            default_company = ""
        if doc["entry_type"] != "company":
            # A thematic or archival document has no single subject firm, so its
            # own title must never stand in for one. Previously this only
            # applied to documents detected as annuaires, so multi-firm surveys
            # that the annuaire test missed - "Parlementaires et financiers",
            # "Valeurs inscrites a la Cote des banquiers a Paris en 1913" -
            # became company nodes that absorbed every board they listed,
            # reaching 162 and 179 directors and outranking the Banque de
            # l'Indochine. Ties in these documents now count only where an
            # entry anchor names an actual firm.
            default_company = ""

        # A single-firm dossier can recover attribution from its own title;
        # an annuaire cannot, and a thematic document has no subject firm.
        fallback = (doc["entry_type"] == "company" and not annuaire
                    and bool(default_company))
        segments = build_segments(text, annuaire, default_company, fallback)

        n_ties = 0
        for seg in segments:
            comp = clean_text(seg["company"])
            # Anchor regexes occasionally capture punctuation instead of a name.
            if comp and not re.search(r"[A-Za-zÀ-ÿ]{3}", comp):
                comp = ""
            comp_norm = normalise_org_name(comp) if comp else ""
            ckey = org_key(comp) if comp else ""
            if ckey and ckey not in company_names:
                company_names[ckey] = {
                    "company_key": ckey,
                    "name": comp_norm,
                    "first_doc_id": doc_id,
                    "n_mentions": 0,
                }
            if ckey:
                company_names[ckey]["n_mentions"] += 1

            for body, default_role, trigger in find_board_lists(seg["text"]):
                for mem in parse_board_list(body, default_role):
                    row = {
                        "doc_id": doc_id,
                        "company_key": ckey,
                        "company_name": comp_norm,
                        "member_raw": mem["member_raw"],
                        "name_clean": mem["name_clean"],
                        "role": mem["role"],
                        "year": seg["year"],
                        "source_ref": seg["source"],
                        "anchor_type": seg["anchor"],
                        "attribution": seg.get("attribution", ""),
                        "trigger": trigger,
                        "annotation": mem["annotation"],
                        "region": doc["region"],
                        "country": doc["country"],
                        "sector": doc["sector"],
                    }
                    if mem["member_type"] == "organisation":
                        row["member_key"] = mem["entity_key"]
                        org_affiliations.append(row)
                    elif member_is_junk(mem["name_clean"]):
                        n_junk += 1
                    else:
                        row["person_key"] = mem["entity_key"]
                        row["surname"] = mem["surname"]
                        row["given"] = mem["given"]
                        row["parse_note"] = mem.get("parse_note", "")
                        affiliations.append(row)
                        pr = person_records[mem["entity_key"]]
                        pr["person_key"] = mem["entity_key"]
                        pr["names"].add(mem["name_clean"])
                        pr["surname"] = mem["surname"]
                        if mem["given"]:
                            pr["given"].add(mem["given"])
                        pr["n_ties"] += 1
                    n_ties += 1

            if ckey:
                for attr, value in parse_attributes(seg["text"]):
                    attributes.append(
                        {
                            "doc_id": doc_id,
                            "company_key": ckey,
                            "company_name": comp_norm,
                            "attribute": attr,
                            "value": value,
                            "year": seg["year"],
                            "source_ref": seg["source"],
                        }
                    )

        seen_xref = set()
        for m in XREF_RE.finditer(text):
            p = m.group("path")
            if p in seen_xref:
                continue
            seen_xref.add(p)
            references.append(
                {
                    "from_doc_id": doc_id,
                    "to_path": p,
                    "to_url": f"https://entreprises-coloniales.fr/{p}",
                }
            )

        report.append(
            {
                "doc_id": doc_id,
                "is_annuaire": int(annuaire),
                "n_chars": len(text),
                "n_segments": len(segments),
                "n_ties": n_ties,
                "n_xrefs": len(seen_xref),
                "entry_type": doc["entry_type"],
            }
        )
        if i % 500 == 0:
            print(f"  parsed {i}/{len(files)} docs, {len(affiliations)} person ties",
                  file=sys.stderr, flush=True)

    # Resolve cross-reference targets to doc_ids.
    from common import doc_id_from_url

    by_path = {}
    for d in docs.values():
        p = re.sub(r"^https?://(?:www\.)?entreprises-coloniales\.fr/", "", d["pdf_url"])
        by_path[p] = d["doc_id"]
    for r in references:
        r["to_doc_id"] = by_path.get(r["to_path"], doc_id_from_url(r["to_url"]))
        r["resolved"] = int(r["to_path"] in by_path)

    sfx = args.out_suffix
    _write(f"affiliations{sfx}.csv", affiliations,
           ["doc_id", "company_key", "company_name", "person_key", "name_clean", "surname",
            "given", "role", "year", "source_ref", "annotation", "region", "country",
            "sector", "anchor_type", "attribution", "trigger", "parse_note",
            "member_raw"])
    _write(f"org_affiliations{sfx}.csv", org_affiliations,
           ["doc_id", "company_key", "company_name", "member_key", "name_clean", "role",
            "year", "source_ref", "annotation", "region", "country", "sector",
            "anchor_type", "trigger", "member_raw"])
    _write(f"company_attributes{sfx}.csv", attributes,
           ["company_key", "company_name", "attribute", "value", "year", "source_ref", "doc_id"])
    _write(f"doc_references{sfx}.csv", references,
           ["from_doc_id", "to_doc_id", "resolved", "to_url", "to_path"])
    _write(f"parse_report{sfx}.csv", report,
           ["doc_id", "entry_type", "is_annuaire", "n_chars", "n_segments", "n_ties", "n_xrefs"])

    persons = []
    for key, pr in person_records.items():
        persons.append(
            {
                "person_key": key,
                "surname": pr["surname"],
                "given_variants": "; ".join(sorted(pr["given"])),
                "name_variants": "; ".join(sorted(pr["names"])),
                "n_name_variants": len(pr["names"]),
                "n_ties": pr["n_ties"],
            }
        )
    persons.sort(key=lambda r: -r["n_ties"])
    _write(f"persons{sfx}.csv", persons,
           ["person_key", "surname", "given_variants", "n_ties", "n_name_variants",
            "name_variants"])

    comps = sorted(company_names.values(), key=lambda r: -r["n_mentions"])
    _write(f"companies_observed{sfx}.csv", comps,
           ["company_key", "name", "n_mentions", "first_doc_id"])

    print(
        f"\ndocs parsed        {len(report)}\n"
        f"person ties        {len(affiliations)}\n"
        f"corporate ties     {len(org_affiliations)}\n"
        f"distinct persons   {len(persons)}\n"
        f"companies observed {len(comps)}\n"
        f"attributes         {len(attributes)}\n"
        f"cross-references   {len(references)}",
        file=sys.stderr,
    )


def _write(name: str, rows: list[dict], fields: list[str]) -> None:
    path = os.path.join(PROC_DIR, name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {path}: {len(rows)} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
