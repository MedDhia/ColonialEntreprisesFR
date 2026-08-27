"""Stage 1 - crawl the site's index pages into a document catalogue.

The site is a set of hand-written territory pages. Structure that carries
meaning:

    <h2 class="pays">            page title (territory)
    <h2 class="premierTitrePays">country / sub-territory
    <h2 class="titreRubrique">   economic sector
    <ul class="LD">              document list
      <li class="LDL"><a href="x.pdf">Title</a>   a document
      <li class="LDL">Group name                  a group header (no link)
      <ul class="DL"> ... </ul>                   that group's documents
        <ul class="SDL"> ... </ul>                a nested sub-group

Outputs
    data/processed/documents.csv          one row per unique PDF
    data/processed/document_listings.csv  one row per (document, classification)
"""

from __future__ import annotations

import csv
import os
import re
import sys
import urllib.parse
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    BASE_URL,
    INDEX_PAGES,
    LEGACY_PAGES,
    REGION_LABELS,
    LIFEDATE_RE,
    PERSON_TITLE_RE,
    clean_text,
    doc_id_from_url,
    ensure_dir,
    fetch,
    split_title,
)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "processed")
CACHE_DIR = os.environ.get("EC_CACHE", "/tmp/ec_cache")

HEADING_CLASSES = {"pays", "premierTitrePays", "titreRubrique", "titrePays"}


class IndexParser(HTMLParser):
    """Walks one territory page, emitting classified document entries."""

    def __init__(self, page: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page = page
        self.page_url = urllib.parse.urljoin(BASE_URL, page)
        self.entries: list[dict] = []

        self.country = ""
        self.sector = ""
        self.page_territory = ""

        self._heading_class: str | None = None
        self._heading_buf: list[str] = []

        # A <li> is open: collect its text and the first PDF link inside it.
        self._in_li = False
        self._li_buf: list[str] = []
        self._li_href: str | None = None
        self._li_all_hrefs: list[str] = []

        # Group nesting. `pending_group` is the last link-less <li>; it becomes
        # the group label when the following nested <ul> opens.
        self.group_stack: list[str] = []
        self._pending_group: str | None = None
        self._ul_stack: list[str] = []

    # -- helpers ----------------------------------------------------------
    def _flush_li(self) -> None:
        if not self._in_li:
            return
        text = clean_text("".join(self._li_buf))
        href = self._li_href
        self._in_li = False
        self._li_buf = []
        self._li_href = None
        hrefs = self._li_all_hrefs
        self._li_all_hrefs = []
        if not text:
            return
        if href:
            self._emit(text, href, hrefs)
            self._pending_group = None
        else:
            # Link-less list item = header for the nested list that follows.
            self._pending_group = text

    def _emit(self, title: str, href: str, all_hrefs: list[str]) -> None:
        pdf_url = urllib.parse.urljoin(self.page_url, href)
        parts = split_title(title)
        self.entries.append(
            {
                "doc_id": doc_id_from_url(pdf_url),
                "pdf_url": pdf_url,
                "source_page": self.page,
                "region": REGION_LABELS.get(self.page, self.page),
                "is_legacy_page": self.page in LEGACY_PAGES,
                "page_territory": self.page_territory,
                "country": self.country,
                "sector": self.sector,
                "group_path": " > ".join(self.group_stack),
                "group_depth": len(self.group_stack),
                "title_raw": title,
                "name_listed": parts["name_listed"],
                "name_normalised": parts["name_normalised"],
                "place_listed": parts["place_listed"],
                "acronym": parts["acronym"],
                "alias": parts["alias"],
                "principal_name": parts["principal_name"],
                "legal_form_listed": parts["legal_form_listed"],
                "year_start": parts["year_start"],
                "year_end": parts["year_end"],
                "head_inverted": parts["head_inverted"],
                "first_paren_is_forename": parts["first_paren_is_forename"],
                "qualifiers": "; ".join(parts["parentheticals"]),
                "note": parts["note"],
                "extra_links": len(all_hrefs) - 1 if all_hrefs else 0,
            }
        )

    # -- HTMLParser hooks -------------------------------------------------
    def handle_starttag(self, tag, attrs):  # noqa: D102
        a = dict(attrs)
        cls = (a.get("class") or "").strip()

        if tag == "h2" and cls in HEADING_CLASSES:
            self._flush_li()
            self._heading_class = cls
            self._heading_buf = []
            return

        if tag == "ul":
            self._flush_li()
            self._ul_stack.append(cls)
            if cls in {"DL", "SDL"} and self._pending_group:
                self.group_stack.append(self._pending_group)
                self._pending_group = None
            else:
                # A fresh top-level list ends any group context.
                if cls == "LD":
                    self.group_stack = []
            return

        if tag == "li":
            self._flush_li()
            self._in_li = True
            self._li_buf = []
            self._li_href = None
            self._li_all_hrefs = []
            return

        if tag == "a" and self._in_li:
            href = a.get("href") or ""
            if href.lower().endswith(".pdf"):
                self._li_all_hrefs.append(href)
                if self._li_href is None:
                    self._li_href = href

    def handle_endtag(self, tag):  # noqa: D102
        if tag == "h2" and self._heading_class:
            text = clean_text("".join(self._heading_buf))
            cls = self._heading_class
            self._heading_class = None
            self._heading_buf = []
            if cls == "pays":
                self.page_territory = text
            elif cls in {"premierTitrePays", "titrePays"}:
                # A page covering several territories marks only the *first*
                # with premierTitrePays; every later one uses titrePays.
                # Handling only the former silently attributed all of
                # Madagascar, the Comoros and Reunion to Djibouti, and all of
                # Guyane, Brazil, Chile and Peru to Guadeloupe-Martinique -
                # 19 territories across 5 pages.
                self.country = text
                self.sector = ""
                self.group_stack = []
            elif cls == "titreRubrique":
                self.sector = text
                self.group_stack = []
            return

        if tag == "li":
            self._flush_li()
            return

        if tag == "ul":
            self._flush_li()
            cls = self._ul_stack.pop() if self._ul_stack else ""
            if cls in {"DL", "SDL"} and self.group_stack:
                self.group_stack.pop()
            self._pending_group = None

    def handle_data(self, data):  # noqa: D102
        if self._heading_class is not None:
            self._heading_buf.append(data)
        elif self._in_li:
            self._li_buf.append(data)


# Occupational words in the gloss that mark a biographical entry.
OCCUPATION_RE = re.compile(
    r"\b(administrateur|planteur|n[eé]gociant|banquier|ing[eé]nieur|industriel|arm[aà]teur|"
    r"armateur|avocat|architecte|commer[cç]ant|entrepreneur|imprimeur|libraire|colon|"
    r"agriculteur|d[eé]put[eé]|s[eé]nateur|gouverneur|r[eé]sident|consul|m[eé]decin|"
    r"pharmacien|notaire|g[eé]om[eè]tre|missionnaire|explorateur|journaliste|directeur|"
    r"pr[eé]sident|g[eé]rant|fondateur|homme d'affaires|riziculteur|fabricant|"
    r"concessionnaire|propri[eé]taire|hu[iî]lier|minotier|distillateur|transporteur)\b",
    re.I,
)

# A gloss that announces monographs on several firms marks the entry as a
# survey, not a company: "notices sur 26 societes d'Indochine", "28
# francaises, 17 anglaises. Notices." Treated as a company, such an entry
# becomes a node that absorbs every board the survey lists - two of them
# reached 254 and 132 directors, outranking the Banque de l'Indochine.
#
# This uses the source's own metadata rather than guessing from titles, and
# matches exactly two entries in the catalogue. Note that a "par <Author>"
# test, which looks like the obvious companion rule, must NOT be used: in
# French addresses "par X" means via X ("Oued-Marsa, par Sidi-Rehane"), so it
# matches 41 entries of which most are genuine firms.
SURVEY_GLOSS_RE = re.compile(
    r"\bnotices?\b(?=.*\bsoci[eé]t[eé]s?\b)|\bnotices?\s+sur\s+\d+|"
    r"\b\d+\s+soci[eé]t[eé]s\b|\bnotices\b\s*\.",
    re.I,
)

# Sectors that hold thematic/archival material rather than single firms.
SOURCE_DOC_SECTORS = (
    "documents generaux",
    "documents généraux",
    "organismes",
    "listes electorales",
    "listes électorales",
    "le systeme monetaire",
    "le système monétaire",
    "amicales",
    "regime electoral",
    "régime électoral",
)


def classify_entry(entry: dict) -> tuple[str, str, str, str, str]:
    """Decide whether a catalogue entry is a firm, a person, or a source document.

    The decisive test is the shape of the first parenthesis. The site inverts
    company names by pushing a generic head into it ("Africaine de Mines
    (Societe)(1900-1903)" is a firm with an operating period), while
    biographical entries carry a forename there ("Jourdan (Adolphe)(1846-1916)").

    Returns (entry_type, person_surname, person_given, birth_year, death_year).
    """
    title = entry["title_raw"]
    sector = entry["sector"].lower()

    if any(k in sector for k in SOURCE_DOC_SECTORS):
        return ("source_document", "", "", "", "")

    # A multi-firm survey is a source document whatever sector it is filed under.
    if SURVEY_GLOSS_RE.search(entry["note"]) or SURVEY_GLOSS_RE.search(title):
        return ("source_document", "", "", "", "")

    # "Surname (Forename)(1846-1916)" - the dominant biographical pattern.
    m = PERSON_TITLE_RE.match(title)
    if m and entry["first_paren_is_forename"] and not entry["head_inverted"]:
        return (
            "person",
            clean_text(m.group("surname")),
            clean_text(m.group("given")),
            m.group("b") or "",
            m.group("d") or "",
        )

    # "Forename SURNAME (1880-1950)" - biographies written the natural way round.
    ld = LIFEDATE_RE.search(title)
    if ld and not entry["head_inverted"]:
        head = title[: ld.start()].strip(" ,;")
        if head and "," not in head and 2 <= len(head.split()) <= 4:
            looks_person = bool(re.search(r"\b[A-ZÉÈÀÂÎÔÛÇ]{2,}\b", head)) or _forename_first(head)
            if looks_person:
                bits = head.split()
                return (
                    "person",
                    bits[-1],
                    " ".join(bits[:-1]),
                    ld.group(1) or "",
                    ld.group(2) or "",
                )

    # No dates, but a forename in the first parenthesis plus an occupational
    # gloss: "Achaque (Antoine), Alger : negociant".
    if (
        entry["first_paren_is_forename"]
        and not entry["head_inverted"]
        and OCCUPATION_RE.search(entry["note"])
    ):
        surname = clean_text(re.split(r"\(", title)[0]).strip(" ,;")
        given = clean_text(entry["qualifiers"].split("; ")[0])
        return ("person", surname, given, entry["year_start"], entry["year_end"])

    return ("company", "", "", "", "")


def _forename_first(head: str) -> bool:
    from common import _is_forename  # local import keeps the public API small

    return _is_forename(head.split()[0])


def main() -> None:
    ensure_dir(OUT_DIR)
    ensure_dir(CACHE_DIR)

    all_entries: list[dict] = []
    for page in INDEX_PAGES:
        cache = os.path.join(CACHE_DIR, page)
        if os.path.exists(cache):
            html = open(cache, "rb").read()
        else:
            html = fetch(urllib.parse.urljoin(BASE_URL, page), delay=0.3)
            with open(cache, "wb") as fh:
                fh.write(html)
        parser = IndexParser(page)
        parser.feed(html.decode("utf-8", errors="replace"))
        parser.close()
        print(f"{page:40s} {len(parser.entries):5d} entries", file=sys.stderr)
        all_entries.extend(parser.entries)

    for e in all_entries:
        etype, surname, given, by, dy = classify_entry(e)
        e["entry_type"] = etype
        e["person_surname"] = surname
        e["person_given"] = given
        e["birth_year"] = by
        e["death_year"] = dy
        if etype == "person":
            # For a person the date parenthesis holds life dates, not the
            # firm's operating period; do not report it in both places.
            e["year_start"] = ""
            e["year_end"] = ""

    # --- document_listings: dedupe on (doc, country, sector, group) --------
    listings: dict[tuple, dict] = {}
    for e in all_entries:
        key = (e["doc_id"], e["country"], e["sector"], e["group_path"])
        if key in listings:
            prev = listings[key]
            pages = set(prev["source_page"].split("; ")) | {e["source_page"]}
            prev["source_page"] = "; ".join(sorted(pages))
            regions = set(prev["region"].split("; ")) | {e["region"]}
            prev["region"] = "; ".join(sorted(regions))
        else:
            row = dict(e)
            listings[key] = row

    listing_rows = list(listings.values())

    # --- documents: one row per PDF, canonical classification -------------
    docs: dict[str, dict] = {}
    for e in all_entries:
        d = docs.get(e["doc_id"])
        # Prefer a non-legacy page, then a deeper (more specific) sector.
        better = (
            d is None
            or (d["is_legacy_page"] and not e["is_legacy_page"])
            or (d["is_legacy_page"] == e["is_legacy_page"] and not d["sector"] and e["sector"])
        )
        if better:
            docs[e["doc_id"]] = dict(e)

    for doc_id, row in docs.items():
        mine = [x for x in listing_rows if x["doc_id"] == doc_id]
        row["n_listings"] = len(mine)
        row["all_regions"] = "; ".join(
            sorted({r for x in mine for r in x["region"].split("; ") if r})
        )
        row["all_sectors"] = "; ".join(sorted({x["sector"] for x in mine if x["sector"]}))

    doc_fields = [
        "doc_id",
        "pdf_url",
        "entry_type",
        "name_listed",
        "name_normalised",
        "acronym",
        "alias",
        "principal_name",
        "place_listed",
        "legal_form_listed",
        "year_start",
        "year_end",
        "person_surname",
        "person_given",
        "birth_year",
        "death_year",
        "region",
        "country",
        "sector",
        "group_path",
        "group_depth",
        "all_regions",
        "all_sectors",
        "n_listings",
        "qualifiers",
        "note",
        "source_page",
        "title_raw",
    ]
    listing_fields = [
        "doc_id",
        "source_page",
        "region",
        "page_territory",
        "country",
        "sector",
        "group_path",
        "group_depth",
        "entry_type",
        "name_normalised",
    ]

    doc_path = os.path.join(OUT_DIR, "documents.csv")
    with open(doc_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=doc_fields, extrasaction="ignore")
        w.writeheader()
        for row in sorted(docs.values(), key=lambda r: r["doc_id"]):
            w.writerow(row)

    listing_path = os.path.join(OUT_DIR, "document_listings.csv")
    with open(listing_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=listing_fields, extrasaction="ignore")
        w.writeheader()
        for row in sorted(listing_rows, key=lambda r: (r["doc_id"], r["country"], r["sector"])):
            w.writerow(row)

    print(f"\nwrote {doc_path}: {len(docs)} unique documents", file=sys.stderr)
    print(f"wrote {listing_path}: {len(listing_rows)} listings", file=sys.stderr)
    from collections import Counter

    print("\nentry_type:", Counter(r["entry_type"] for r in docs.values()), file=sys.stderr)


if __name__ == "__main__":
    main()
