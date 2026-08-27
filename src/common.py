"""Shared helpers: polite HTTP fetching, slugs, French name normalisation."""

from __future__ import annotations

import hashlib
import os
import random
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://entreprises-coloniales.fr/"
USER_AGENT = (
    "ColonialEntreprisesFR-research-crawler/1.0 "
    "(academic dataset construction; contact via repository)"
)

# Index pages that make up the whole site (from sitemap.xml plus the
# per-territory pages linked from the homepage).
INDEX_PAGES = [
    "empire.html",
    "maroc.html",
    "algerie.html",
    "tunisie.html",
    "proche-orient.html",
    "afrique-occidentale-francaise.html",
    "afrique-equatoriale-francaise.html",
    "madagascar-et-djibouti.html",
    "inde.html",
    "indochine.html",
    "inde-et-indochine.html",
    "pacifique.html",
    "antilles-guyane.html",
]

# `inde-et-indochine.html` is a legacy composite page duplicating
# `indochine.html` + `inde.html`; it is crawled (it holds a few unique
# documents) but deprioritised when picking a document's canonical region.
LEGACY_PAGES = {"inde-et-indochine.html"}

REGION_LABELS = {
    "empire.html": "Empire (transversal)",
    "maroc.html": "Maroc",
    "algerie.html": "Algerie",
    "tunisie.html": "Tunisie",
    "proche-orient.html": "Proche-Orient",
    "afrique-occidentale-francaise.html": "Afrique occidentale francaise",
    "afrique-equatoriale-francaise.html": "Afrique equatoriale francaise",
    "madagascar-et-djibouti.html": "Madagascar et Djibouti",
    "inde.html": "Inde francaise",
    "indochine.html": "Indochine",
    "inde-et-indochine.html": "Inde et Indochine",
    "pacifique.html": "Pacifique",
    "antilles-guyane.html": "Antilles-Guyane",
}


def fetch(url: str, retries: int = 4, timeout: int = 180, delay: float = 0.0) -> bytes:
    """GET a URL with exponential backoff. Returns raw bytes."""
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if delay:
                time.sleep(delay)
            return data
        except Exception as exc:  # noqa: BLE001 - network layer, retry everything
            last = exc
            if attempt < retries:
                time.sleep((2**attempt) + random.random())
    raise RuntimeError(f"failed to fetch {url}: {last}")


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def slugify(text: str, maxlen: int = 80) -> str:
    s = strip_accents(text).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:maxlen] or "x"


def doc_id_from_url(pdf_url: str) -> str:
    """Stable, human-readable id derived from the PDF path."""
    path = urllib.parse.urlsplit(pdf_url).path
    path = re.sub(r"^/+", "", path)
    path = re.sub(r"\.pdf$", "", path, flags=re.I)
    parts = [p for p in path.split("/") if p]
    stem = parts[-1] if parts else path
    folder = parts[-2] if len(parts) > 1 else ""
    slug = slugify(f"{folder}-{stem}", 70)
    # Short hash guards against collisions after slug normalisation.
    h = hashlib.sha1(path.encode("utf-8")).hexdigest()[:6]
    return f"{slug}-{h}"


WS_RE = re.compile(r"[\s ]+")


def clean_text(text: str) -> str:
    text = text.replace(" ", " ")
    return WS_RE.sub(" ", text).strip()


# --- French corporate/person name handling -------------------------------

REF_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "reference"
)


def _load_reference(name: str) -> list[str]:
    path = os.path.join(REF_DIR, name)
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append(line)
    return out


PLACES = {strip_accents(p).lower() for p in _load_reference("places.txt")}
FORENAMES = {strip_accents(p).lower() for p in _load_reference("forenames.txt")}

# The site inverts names so that lists sort on the distinctive word, pushing the
# generic head into the first parenthesis:
#   "Agricole ... de l'Indochine (Societe)(Safimic), Hanoi"
#   "Abattoirs municipaux ... au Maroc (Societe generale des), Casablanca"
# CORPORATE_HEAD_RE matches such an invertible head.
CORPORATE_HEAD_RE = re.compile(
    r"^(?:soci[eé]t[eé]s?|compagnies?|cie|s\.?\s?a\.?|sarl|s\.?a\.?r\.?l\.?|banques?|cr[eé]dit|"
    r"union|syndicats?|entreprises?|[eé]tablissements|[eé]ts|consortium|office|omnium|groupe|"
    r"manufactures?|plantations?|domaines?|mines?|charbonnages|comptoirs?|associations?|caisses?|"
    r"chambres?|ports?|usines?|fermes?|h[oô]tels?|cin[eé]mas?|imprimeries?|librairies?|brasseries?|"
    r"distilleries?|huileries?|salines|scieries?|tanneries?|raffineries?|sucreries?|verreries?|"
    r"fonderies?|filatures?|papeteries?|soci[eé]t[eé]\s+anonyme|agence|agences|"
    r"anciens?\s+[eé]tablissements|ateliers?)\b",
    re.I,
)
ARTICLE_RE = re.compile(r"^(?:la|le|les|l['’]|the|of|die|el)$", re.I)

LEGAL_FORM_RE = re.compile(
    r"\b(soci[eé]t[eé]\s+anonyme(?:\s+\w+)?|s\.?\s?a\.?r\.?l\.?|sarl|s\.?\s?a\.?|"
    r"soci[eé]t[eé]\s+en\s+commandite(?:\s+\w+){0,3}|soci[eé]t[eé]\s+civile(?:\s+\w+){0,3}|"
    r"soci[eé]t[eé]\s+coop[eé]rative|soci[eé]t[eé]\s+[aà]\s+responsabilit[eé]\s+limit[eé]e|"
    r"soci[eé]t[eé]\s+en\s+nom\s+collectif|limited|ltd|gmbh|n\.?v\.?|"
    r"soci[eé]t[eé]\s+indig[eé]ne\s+de\s+pr[eé]voyance)\b",
    re.I,
)

PAREN_RE = re.compile(r"\(([^()]*)\)")
YEAR = r"1[5-9]\d{2}|20\d{2}"
DATERANGE_RE = re.compile(
    rf"^\s*(?:ca\.?\s*)?(?P<y1>{YEAR})\s*(?:[-–—]\s*(?:ca\.?\s*)?(?P<y2>{YEAR})?)?\s*$"
)
ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9&.\-]{1,14}$")
INITIALS_RE = re.compile(r"^(?:[A-ZÉÈÀÂÎÔÛÇ]\.\s*){1,3}$")

CIRCA = r"(?:ca?\.?\s*)?"
# Death year may be unknown ("1872-?") or approximate ("1876-c. 1939").
LIFEDATE_RE = re.compile(
    rf"\(\s*{CIRCA}({YEAR})\s*[-–—]\s*{CIRCA}(?:({YEAR})|\?)?\s*\)"
)
# "Bec (Alphonse)(1878-1938)" -> surname "Bec", given "Alphonse"
PERSON_TITLE_RE = re.compile(
    rf"^(?P<surname>[^(]{{2,60}}?)\s*\((?P<given>[A-ZÉÈÀÂÎÔÛÇ][^()]{{0,40}})\)\s*\("
    rf"\s*{CIRCA}(?P<b>{YEAR})?\s*[-–—]?\s*{CIRCA}(?:(?P<d>{YEAR})|\?)?\s*\)"
)


def personal_name_in(paren: str) -> str:
    """Return a personal name carried by a parenthetical, else "".

    Catches both plain forenames ("Alphonse") and fuller personal names whose
    first token is a forename ("Henri de Laborde", "Lucien Deyme"). Used to
    record the named principal of an eponymous firm, which is a tie in its own
    right, without reclassifying the firm as a person.
    """
    p = clean_text(paren)
    if not p or re.search(r"\d", p):
        return ""
    if CORPORATE_HEAD_RE.match(p) or ARTICLE_RE.match(p.strip()):
        return ""
    p = HONORIFIC_RE.sub("", p)
    p = re.sub(r"^(?:anc\.?|ancienne?s?|ex-?)\s+", "", p, flags=re.I).strip()
    tokens = [t for t in p.replace("’", "'").split() if t]
    if not tokens or len(tokens) > 5:
        return ""
    first = tokens[0]
    if not (_is_single_forename(first) or INITIALS_RE.match(first)):
        return ""
    # Remaining tokens must be name-like: capitalised words, particles, or "et".
    for t in tokens[1:]:
        if re.match(r"^(?:de|d'|du|des|le|la|van|von|di|da|dit|et|&|ses|fils|fr[eè]res)$", t, re.I):
            continue
        if re.match(r"^[A-ZÉÈÀÂÎÔÛÇ][\w'’.-]*$", t):
            continue
        return ""
    return clean_text(p)


HONORIFIC_RE = re.compile(
    r"^(?:dr|docteur|m|mme|mlle|me|mgr|cdt|commandant|g[eé]n[eé]ral|g[eé]n|col|capitaine|"
    r"cap|lt|lieutenant|abb[eé]|p[eè]re|sir|lord)\.?\s+",
    re.I,
)
# Nobiliary / Dutch-German particles that trail a forename in these titles:
# "Pierre-Eugene de", "Ch. et Louis d'".
PARTICLE_RE = re.compile(r"\s+(?:de|d['’]|du|des|le|la|van|von|di|da|dit)\s*$", re.I)


def _is_single_forename(token: str) -> bool:
    t = strip_accents(token).lower().strip(" .")
    if not t:
        return False
    if t in FORENAMES:
        return True
    # A hyphenated compound is a forename if every element is one:
    # "Jean-Baptiste", "Edouard-Raphael", "Pierre-Eugene".
    if "-" in t:
        bits = [b for b in t.split("-") if b]
        return len(bits) > 1 and all(b in FORENAMES for b in bits)
    return False


def _is_forename(text: str) -> bool:
    """True if a parenthetical looks like one or more personal forenames.

    Accepts "Alphonse", "Jean-Baptiste", "J.", "Ch. et Louis d'",
    "Auguste Antoine Alexandre", "Dr Alexandre"; rejects corporate aliases
    and acronyms such as "Socfin", "CFSO", "Saint-Gobain".
    """
    t = clean_text(text)
    t = HONORIFIC_RE.sub("", t)
    t = PARTICLE_RE.sub("", t).strip(" ,")
    if not t:
        return False
    # "Ch. et Louis", "Emile et Leopold" - joint entries for brothers/partners.
    groups = [g.strip() for g in re.split(r"\s+et\s+|\s*&\s*|\s*,\s*", t) if g.strip()]
    if not groups or len(groups) > 3:
        return False
    for g in groups:
        if INITIALS_RE.match(g + (" " if not g.endswith(".") else "")) or INITIALS_RE.match(g):
            continue
        tokens = [x for x in g.split() if x]
        if not tokens or len(tokens) > 3:
            return False
        if not all(_is_single_forename(tok) or INITIALS_RE.match(tok) for tok in tokens):
            return False
    return True


def _place_tail(head: str) -> tuple[str, str]:
    """Peel trailing place segments off a comma-separated name head.

    "Acconage et de charbons de Tunisie, Tunis" -> ("Acconage ... de Tunisie", "Tunis")
    "Africaine de Travaux, Alger, puis Oran"    -> (..., "Alger; puis Oran")
    """
    segs = [s.strip() for s in head.split(",")]
    places: list[str] = []
    while len(segs) > 1:
        cand = segs[-1]
        probe = re.sub(r"^(?:puis|et|ou|then|anc\.?|ex-?)\s+", "", cand, flags=re.I).strip(" .…")
        if probe and strip_accents(probe).lower() in PLACES:
            places.insert(0, cand)
            segs.pop()
        else:
            break
    return ", ".join(segs).strip(" ,;"), "; ".join(places)


def split_title(title: str) -> dict:
    """Parse a catalogue entry title into its components.

    The titles follow a consistent hand-keyed grammar:
        <distinctive name> (<generic head>)(<acronym|dates>), <place> : <gloss>

    Returns a dict of: name_listed, name_normalised, place_listed,
    parentheticals, note, acronym, legal_form_listed, year_start, year_end,
    head_inverted, first_paren_is_forename.
    """
    title = clean_text(title)
    note = ""
    # The first colon splits the name from the editorial gloss. It may follow a
    # closing parenthesis with no space: "Abri familial oranais (L')(1928): Oran".
    m = re.search(r":(?:\s|$)", title)
    if m:
        note = title[m.end() :].strip()
        title = title[: m.start()].strip()

    parens = PAREN_RE.findall(title)
    head = PAREN_RE.sub("", title)
    head = clean_text(head.replace(" ,", ",")).strip(" ,;")
    head, place = _place_tail(head)

    year_start = year_end = ""
    acronym = ""
    aliases: list[str] = []
    legal_form = ""
    invertible = ""
    for p in parens:
        p = clean_text(p)
        if not p:
            continue
        dm = DATERANGE_RE.match(p)
        if dm and not year_start:
            year_start = dm.group("y1") or ""
            year_end = dm.group("y2") or ""
            continue
        lf = LEGAL_FORM_RE.search(p)
        if lf and not legal_form:
            legal_form = clean_text(lf.group(1))
            # A parenthesis like "S.A., 1916" also carries the founding year.
            ym = re.search(rf"\b({YEAR})\b", p)
            if ym and not year_start:
                year_start = ym.group(1)
            continue
        if not invertible and (CORPORATE_HEAD_RE.match(p) or ARTICLE_RE.match(p.strip())):
            invertible = p
            continue
        if _is_forename(p):
            continue
        # Anything left is a secondary designation: an acronym, a trade name,
        # or the controlling group ("Safimic", "CFSO", "Pernod", "Saint-Gobain").
        if not acronym and ACRONYM_RE.match(p):
            acronym = p
        else:
            aliases.append(p)

    if invertible:
        joiner = "" if invertible.endswith(("'", "’")) else " "
        name_norm = f"{invertible}{joiner}{head}"
    else:
        name_norm = head

    return {
        "name_listed": title,
        "name_normalised": clean_text(name_norm),
        "place_listed": place,
        "parentheticals": parens,
        "note": note,
        "acronym": acronym,
        "alias": "; ".join(aliases),
        "principal_name": personal_name_in(parens[0]) if parens else "",
        "legal_form_listed": legal_form,
        "year_start": year_start,
        "year_end": year_end,
        "head_inverted": bool(invertible),
        "first_paren_is_forename": bool(parens) and _is_forename(parens[0]),
    }


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
