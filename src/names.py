"""Parsing and normalisation of French personal and corporate names.

Board lists in these sources name people in several registers within a single
line: "MM. Georges Despret, présid. ; A. R. Fontaine (Distill. Indoch.),
admin.-dél. ; Dr H.-A. Van Nierop, baron Carton de Wiart, administrateurs",
and sometimes surname-first: "PHILIPPAR (Edmond)[Credit foncier]".

Two jobs live here:

1. Splitting a raw name string into honorific / given / particle / surname.
   Given names are identified from the reference forename list, falling back
   to a positional heuristic for forenames not on it. This matters because the
   surname is what entity resolution keys on.

2. Deciding whether a board member is a natural person or a company. Corporate
   directorships are common in this corpus ("la Societe centrale d'etudes ...,
   vice-president") and are a company-to-company tie, not a person-to-company
   one, so they must not be silently parsed as people.

Entity resolution is deliberately conservative and reversible: every tie keeps
the raw string, and person_key is only a *suggested* grouping (normalised
surname plus first given initial). See docs/CODEBOOK.md.
"""

from __future__ import annotations

import re

from common import FORENAMES, INITIALS_RE, clean_text, slugify, strip_accents

# Titles and honorifics that precede a name in these sources.
HONORIFICS = (
    r"mm|m|mme|mlle|me|mgr|dr|docteur|pr|prof|st|sir|lord|lady|"
    r"baron|baronne|comte|comtesse|vicomte|vicomtesse|marquis|marquise|duc|duchesse|"
    r"g[eé]n[eé]ral|g[eé]n|colonel|col|commandant|cdt|capitaine|cap|lieutenant|lt|"
    r"amiral|abb[eé]|p[eè]re|mah|si|sidi|hadj|cheikh|ca[iï]d|bachagha|agha"
)
HONORIFIC_TOKEN_RE = re.compile(rf"^(?:{HONORIFICS})\.?$", re.I)
LEADING_MM_RE = re.compile(r"^\s*(?:MM\.|M\.|Messieurs|Mmes|Mme|Mlle)\s*", re.I)

# Nobiliary and foreign particles that belong to the surname.
PARTICLES = {
    "de", "d", "du", "des", "le", "la", "les", "van", "von", "der", "den", "ten",
    "di", "da", "do", "dos", "del", "della", "el", "al", "ben", "bin", "ibn",
    "mac", "mc", "o", "saint", "st", "y",
}

# Words that mark a board member as a company rather than a person.
ORG_MARKERS = re.compile(
    r"\b(soci[eé]t[eé]|compagnie|cie|banque|banco|cr[eé]dit|comptoir|omnium|consortium|"
    r"[eé]tablissements|[eé]ts|entreprise|syndicat|union|caisse|office|groupe|"
    r"manufacture|plantations?|domaines?|charbonnages|mines de|usines?|"
    r"holding|trust|corporation|company|limited|ltd|gmbh|s\.?a\.?r\.?l\.?|"
    r"agence|administration|gouvernement|[eé]tat|tr[eé]sor|minist[eè]re|"
    r"chambre de commerce|coop[eé]rative|mutuelle|assurances?)\b",
    re.I,
)
# A leading article is the giveaway for a corporate director: "la Banque
# privee", "la Societe centrale d'etudes". The following word must be
# capitalised, or the rule also swallows ordinary prose fragments such as
# "Les travaux comme..." and files them as companies.
# Deliberately NOT re.I: the flag would make the uppercase class match lower
# case as well, which is exactly the distinction being drawn here.
ORG_ARTICLE_RE = re.compile(r"^(?:[Ll]a|[Ll]e|[Ll]es|[Ll]['’]|LA|LE|LES)\s*[A-ZÉÈÀÂÎÔÛÇ]")

# Occupational or descriptive tails that follow a name and are not part of it.
DESCRIPTOR_RE = re.compile(
    r"^(?:administrateur|ing[eé]nieur|industriel|n[eé]gociant|banquier|avocat|architecte|"
    r"entrepreneur|propri[eé]taire|colon|planteur|agriculteur|commer[cç]ant|docteur|"
    r"d[eé]put[eé]|s[eé]nateur|conseiller|juge|pr[eé]sident|vice-pr[eé]sident|tr[eé]sorier|"
    r"doyen|membre|directeur|g[eé]rant|chevalier|officier|commandeur|ancien|"
    r"pharmacien|notaire|courtier|armateur|imprimeur|libraire|fabricant|"
    r"capitaine|lieutenant|colonel|g[eé]n[eé]ral|inspecteur|receveur|percepteur)\b",
    re.I,
)

# Footnote markers surface as bare digits inside extracted board lists.
FOOTNOTE_NOISE_RE = re.compile(r"(?<=\s)\d{1,2}(?=\s)")

# "PHILIPPAR (Edmond)" / "Chabert Pierre" - surname-first registers.
SURNAME_FIRST_PAREN_RE = re.compile(
    r"^(?P<surname>[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ'’\- ]{1,40}?)\s*\((?P<given>[^)]{1,40})\)\s*$"
)


# The compiler restores a forename the source abbreviated, in two ways. He
# expands an initial in place - "G[eorges] Hersent", "A[nthony] Kroller" - or
# supplies the whole name ahead of the surname - "[Charles] Michel-Cote".
#
# This rule used to accept only parentheses, "P(aul) Delorme". That form occurs
# **zero** times in the corpus; the bracketed one occurs 7,802 times and the
# leading one 7,388, and both were being discarded as annotations, throwing
# away 15,190 forenames the compiler had gone to the trouble of supplying.
# Both delimiters are now accepted.
EXPANDED_INITIAL_RE = re.compile(
    r"\b([A-ZÉÈÀÂÎÔÛÇ])[(\[]([a-zéèêëàâîïôöûüùç'-]{1,12})[)\]]")
# A leading bracketed forename. Unlike the in-place form this one is ambiguous
# - "[Phosphates] Oceanie" has the same shape - so the bracketed word must be
# an attested forename, and a capitalised surname must follow it.
LEADING_FORENAME_RE = re.compile(
    r"^\[([A-ZÉÈÀÂÎÔÛÇ][a-zéèêëàâîïôöûüùç'-]{2,14})\]\s+(?=[A-ZÉÈÀÂÎÔÛÇ])")


def expand_leading_forename(text: str) -> str:
    """Fold a leading "[Forename] Surname" bracket into the name."""
    m = LEADING_FORENAME_RE.match(text.lstrip())
    if not m:
        return text
    if strip_accents(m.group(1)).lower() not in FORENAMES:
        return text
    return LEADING_FORENAME_RE.sub(m.group(1) + " ", text.lstrip(), count=1)


def tidy_fragment(text: str) -> str:
    """Normalise French typography, expand in-place initials, strip footnotes."""
    t = clean_text(text)
    t = t.replace("’", "'")
    t = EXPANDED_INITIAL_RE.sub(r"\1\2", t)
    t = FOOTNOTE_NOISE_RE.sub(" ", t)
    t = re.sub(r"\s+([,;:.])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


# Newspaper and periodical titles. They appear inside the dated source
# citations, and when a citation is absorbed into a board list the title looks
# exactly like a member name. They are sources, not entities, so they are
# rejected outright rather than recorded as companies.
PUBLICATION_RE = re.compile(
    r"\b(gazette|journal|journ[eé]e|bulletin|[eé]cho|d[eé]p[eê]che|cote\s+de|annales|"
    r"revue|presse|informations?|courrier|moniteur|s[eé]maphore|avenir|opinion|"
    r"tribune|libert[eé]|progr[eè]s|r[eé]veil|vigie|petit\s+\w+|temps|figaro|matin|"
    r"illustration|illustr[eé]e|hebdomadaire|quotidien|annuaire|palais|"
    r"recueil|affiches|petites\s+affiches|r[eé]pertoire|almanach|m[eé]morial|"
    r"documentation|valeurs\s+inscrites|cote\s+des\s+banquiers|"
    r"dictionnaire|who'?s\s+who|notices?\s+biographiques|catalogue\s+g[eé]n[eé]ral|"
    r"agence\s+[eé]conomique|documents?\s+politiques)\b",
    re.I,
)
# Balance-sheet and accounting line items, which sit in tables next to boards.
ACCOUNTING_RE = re.compile(
    r"^(?:disponibilit[eé]s?|portefeuille|immobilisations?|amortissements?|r[eé]serves?|"
    r"b[eé]n[eé]fices?|pertes?|provisions?|cr[eé]anciers?|d[eé]biteurs?|cr[eé]diteurs?|"
    r"esp[eè]ces?|caisse|banques?|stocks?|marchandises?|titres?|participations?|"
    r"fournisseurs?|clients?|report|solde|totaux?|total|passif|actif|"
    r"frais\s+\w+|charges?|produits?|recettes?|d[eé]penses?|imp[oô]ts?|"
    r"exc[eé]dent|dotation|capital\s+\w*)\.?$",
    re.I,
)


def looks_like_org(name: str) -> bool:
    n = clean_text(name)
    if not n:
        return False
    if ORG_MARKERS.search(n):
        return True
    if ORG_ARTICLE_RE.match(n):
        # Two tokens for the spaced form ("la Banque privee"); an elided
        # article fuses into one token but is still a company ("L'Alfa").
        if len(n.split()) >= 2 or n[1:2] in {"'", "’"}:
            return True
    return False


def _is_forename_token(tok: str) -> bool:
    t = strip_accents(tok).lower().strip(".")
    if t in FORENAMES:
        return True
    if "-" in t:
        bits = [b for b in t.split("-") if b]
        return len(bits) > 1 and all(b in FORENAMES for b in bits)
    return False


def parse_person_name(raw: str) -> dict:
    """Split a raw personal name into its parts.

    Returns honorific, given, initials, surname, name_clean, person_key,
    and `parse_note` describing which rule fired.
    """
    out = {
        "name_raw": clean_text(raw),
        "honorific": "",
        "given": "",
        "surname": "",
        "name_clean": "",
        "person_key": "",
        "parse_note": "",
    }
    n = tidy_fragment(raw).strip(" ,;.")
    n = LEADING_MM_RE.sub("", n).strip()
    if not n:
        return out

    # Surname-first with the forename in parentheses.
    m = SURNAME_FIRST_PAREN_RE.match(n)
    if m:
        surname = clean_text(m.group("surname")).title() if m.group("surname").isupper() else clean_text(m.group("surname"))
        out.update(
            given=clean_text(m.group("given")),
            surname=surname,
            parse_note="surname_first_paren",
        )
        out["name_clean"] = f"{out['given']} {out['surname']}".strip()
        out["person_key"] = make_person_key(out["surname"], out["given"])
        return out

    tokens = [t for t in n.split() if t]

    honorifics = []
    while tokens and HONORIFIC_TOKEN_RE.match(tokens[0]):
        honorifics.append(tokens.pop(0))
    if not tokens:
        return out

    given: list[str] = []
    # 1. Leading initials: "A. R. Fontaine", "H.-A. Van Nierop".
    while tokens and (
        INITIALS_RE.match(tokens[0]) or re.match(r"^[A-ZÉÈÀÂÎÔÛÇ](?:\.-?[A-ZÉÈÀÂÎÔÛÇ])*\.$", tokens[0])
    ):
        if len(tokens) == 1:
            break  # an initial alone is not a surname
        given.append(tokens.pop(0))
    # 2. Leading recognised forenames: "Georges Despret", "Jean-Baptiste Roux".
    while len(tokens) > 1 and _is_forename_token(tokens[0]):
        given.append(tokens.pop(0))

    note = "initials_or_forename" if given else ""

    # 3. Surname-first without parentheses: "Chabert Pierre", "Bisch Rene".
    #    Only when the last token is a recognised forename and the first is not,
    #    which is what distinguishes it from the ordinary "Georges Despret".
    if not given and len(tokens) == 2 and _is_forename_token(tokens[1]) and not _is_forename_token(tokens[0]):
        out.update(
            honorific=" ".join(honorifics),
            given=tokens[1],
            surname=tokens[0],
            parse_note="surname_first_bare",
        )
        out["name_clean"] = clean_text(f"{tokens[1]} {tokens[0]}")
        out["person_key"] = make_person_key(tokens[0], tokens[1])
        return out

    # 4. Fallback: an unrecognised forename in first position. Refused when the
    #    next token is a particle, because there "Carton de Wiart" is one
    #    compound surname, not a forename plus surname.
    if not given and len(tokens) >= 2:
        first, rest = tokens[0], tokens[1:]
        first_is_particle = strip_accents(first).lower().strip(".'") in PARTICLES
        next_is_particle = strip_accents(rest[0]).lower().strip(".'") in PARTICLES
        rest_all_particles = all(strip_accents(t).lower().strip(".'") in PARTICLES for t in rest)
        if (
            not first_is_particle
            and not next_is_particle
            and not rest_all_particles
            and re.match(r"^[A-ZÉÈÀÂÎÔÛÇ][a-zéèêëàâäîïôöûüùç'’-]+$", first)
        ):
            given.append(tokens.pop(0))
            note = "positional_forename"

    surname = " ".join(tokens).strip(" ,;.")
    out.update(
        honorific=" ".join(honorifics),
        given=" ".join(given),
        surname=surname,
        parse_note=note or "surname_only",
    )
    out["name_clean"] = clean_text(f"{out['given']} {surname}")
    out["person_key"] = make_person_key(surname, out["given"])
    return out


def make_person_key(surname: str, given: str) -> str:
    """Suggested grouping key: normalised surname + first given initial.

    Conservative on purpose. "A. R. Fontaine" and "Auguste-Raphael Fontaine"
    collapse to fontaine-a, while "Leonard Fontaine" stays separate as
    fontaine-l. Same-surname-same-initial people are *not* distinguished; this
    is the dataset's main known limitation and is documented as such.
    """
    s = strip_accents(surname).lower()
    s = re.sub(r"[^a-z\s'-]", "", s)
    # Keep particles in the key: "de margerie" and "margerie" are not merged,
    # since merging them would be an unrecoverable decision.
    s = re.sub(r"\s+", "-", s.strip())
    s = slugify(s, 50)
    if not s:
        return ""
    initial = ""
    g = strip_accents(given).strip()
    if g:
        initial = re.sub(r"[^a-z]", "", g[:1].lower())
    return f"{s}-{initial}" if initial else s


def normalise_org_name(raw: str) -> str:
    """Light normalisation of a company name for matching."""
    n = tidy_fragment(raw).strip(" ,;.*")
    n = re.sub(r"^(?:la|le|les|l')\s+", "", n, flags=re.I)
    n = re.sub(r"\s*\[[^\]]*\]", "", n)
    return clean_text(n)


# A predecessor or former name appended to the current one:
# "Omnium nord-africain (Anct Bonnaud et Cie)", "Marocaine metallurgique (anc.
# Ets Bouvier)". The tail names a different firm, so it must not enter the key.
PREDECESSOR_TAIL_RE = re.compile(
    # The leading \b matters: without it "ex-?" matches inside "Alex." and
    # truncates the name at the third character.
    r"\s*[\(,]?\s*\b(?:anct?\.?|ancienne?(?:ment)?|anciens?|ex-?|pr[eé]c[eé]demment|"
    r"nouvelle\s+d[eé]nomination|puis|devenue?)\b.*$",
    re.I,
)


STOPWORD_RE = re.compile(
    r"\b(societe|ste|s|anonyme|anon|an|cie|compagnie|comp|francaise|francais|"
    r"generale|general|nouvelle|nouveau|de|du|des|d|la|le|les|l|et|en|a|au|aux|"
    r"pour|sur|the|of|and)\b")


# Slugs that are nothing but a legal form or an article.
GENERIC_ONLY = {
    "societe", "societeanonyme", "societeanon", "societeanon", "ste", "steanon",
    "compagnie", "cie", "lacompagnie", "lasociete", "entreprise", "entreprises",
    "etablissements", "ets", "etablissement", "groupe", "syndicat", "union",
    "comptoir", "consortium", "omnium", "banque", "credit", "caisse", "office",
    "anonyme", "nouvelle", "generale", "francaise",
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", strip_accents(text).lower())


def org_key(raw: str) -> str:
    """Matching key for a company name: accent- and stopword-stripped slug.

    Two guards, both of which only fire where the plain rule yields nothing,
    so no existing key changes:

    - The predecessor clause is stripped only when real name text precedes it.
      `PREDECESSOR_TAIL_RE` ends in `.*$`, so on a name that *begins*
      "Anciens Établissements Ch. Peyrissac et Cie" it matches at position 0
      and consumes the whole name. That convention is common in French
      colonial business, and Peyrissac alone lost 72 observations to it.
    - A name made entirely of legal forms and stopwords - "Société générale" -
      falls back to the slug of the whole name rather than to an empty key,
      which would drop the row from every edge file.
    """
    name = normalise_org_name(raw)
    m = PREDECESSOR_TAIL_RE.search(name)
    if m and m.start() >= 4:
        name = name[:m.start()]
    n = STOPWORD_RE.sub(" ", strip_accents(name).lower())
    n = re.sub(r"[^a-z0-9]+", "", n)
    if n:
        return n
    # Fall back to the *original* name, not the truncated one: truncation can
    # leave a bare "Compagnie," whose slug is a generic key several unrelated
    # firms would share.
    fallback = _slug(normalise_org_name(raw))
    # ...but a name that is *only* a legal form is not a firm. Keying it would
    # invent a node called "Société" that unrelated observations pile into,
    # which is worse than leaving the row unattributed.
    return "" if fallback in GENERIC_ONLY else fallback
