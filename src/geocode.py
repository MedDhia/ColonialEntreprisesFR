"""Stage 6c - place each firm at a city, below the level of its colony.

    python3 src/geocode.py            # writes data/processed/company_places.csv

The dataset files a firm under a *territory* — Indochine, Maroc. That is the
unit the source indexes by, and it is too coarse to see that Saigon and Hanoi
were largely separate business worlds, or that most "colonial" firms were run
from Paris. This stage recovers the city.

**Two fields, in order of trust.** `place_listed` comes from the catalogue
title and is a clean city name; it exists for 1,692 firms. `head_office_observed`
is transcribed prose — *"Paris, 1, rue de Stockholm. Tél. : LAB. 18-34"* — and
exists for 3,970. The first is used where present, the second parsed otherwise,
and `source_field` records which, so a sceptical reader can drop the weaker
half.

**Why parse a prefix rather than search the whole string.** A head-office line
is `<city>, <street address>`, and Paris street names include *rue de Rome*,
*rue de Constantinople* and *rue d'Alger*. Searching the whole string for city
names would place a Paris firm in Rome. So the string is cut at the first
digit or street word, and only that prefix — which is where the city is — gets
matched. The prefix is also why *"le siège social est à Paris"* resolves: the
match is on containment within a short, address-free span.

**The gazetteer is curated, not geocoded.** `data/reference/places_geo.csv`
holds 176 cities with coordinates, the territory they sit in, and their
variant spellings. Hand-built because the names are historical — Bône, not
Annaba; Tourane, not Da Nang — and no modern geocoding service returns them
reliably. It is an input: editing it changes the output.

Coverage is partial and is reported rather than smoothed over. A firm with no
recoverable city is written with an empty `city`, not guessed.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_network import read_csv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAZETTEER = os.path.join(ROOT, "data", "reference", "places_geo.csv")
OUT = os.path.join(ROOT, "data", "processed", "company_places.csv")

# Everything from here on is street address, not city.
ADDRESS_RE = re.compile(
    r"\b(?:\d|rue|rues|avenue|av\.|boulevard|bd\.?|place|quai|impasse|passage|"
    r"immeuble|square|allée|cours|faubourg|villa|cité|route|chemin|"
    r"b\.?p\.?|boîte|casier|tél|telephone|téléphone)\b",
    re.IGNORECASE)


def fold(text: str) -> str:
    """Accent- and case-insensitive key. The sources spell Saigon four ways."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def load_gazetteer() -> tuple[dict[str, str], dict[str, dict]]:
    cities: dict[str, dict] = {}
    index: dict[str, str] = {}
    with open(GAZETTEER, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            cities[row["city"]] = row
            index[fold(row["city"])] = row["city"]
            for alias in (row["aliases"] or "").split("; "):
                if alias:
                    index[fold(alias)] = row["city"]
    return index, cities


def match_city(text: str, index: dict[str, str]) -> str | None:
    """Longest-name-first match inside `text`, on the folded forms.

    Longest first so that Saint-Louis is not swallowed by a hypothetical
    Saint, and Pointe-Noire is not read as Pointe-a-Pitre's prefix.
    """
    key = fold(text)
    if not key:
        return None
    if key in index:
        return index[key]
    for name in sorted(index, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", key):
            return index[name]
    return None


def head_office_prefix(text: str) -> str:
    return ADDRESS_RE.split(text, maxsplit=1)[0].strip(" ,;:.-–—")


def resolve(companies, index) -> list[dict]:
    rows = []
    for c in companies:
        city = source = raw = ""
        listed = (c.get("place_listed") or "").split(";")[0].strip()
        if listed:
            hit = match_city(listed, index)
            if hit:
                city, source, raw = hit, "place_listed", listed
        if not city and c.get("head_office_observed"):
            prefix = head_office_prefix(c["head_office_observed"])
            hit = match_city(prefix, index) if prefix else None
            if hit:
                city, source, raw = hit, "head_office_observed", prefix[:80]
        rows.append({"company_id": c["company_id"], "name": c.get("name", ""),
                     "city": city, "source_field": source, "place_raw": raw})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    index, cities = load_gazetteer()
    companies = read_csv("companies.csv")
    rows = resolve(companies, index)

    for r in rows:
        g = cities.get(r["city"], {})
        r["lat"] = g.get("lat", "")
        r["lon"] = g.get("lon", "")
        r["city_territory"] = g.get("territory", "")
        r["group"] = g.get("group", "")

    fields = ["company_id", "name", "city", "lat", "lon", "city_territory",
              "group", "source_field", "place_raw"]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    placed = [r for r in rows if r["city"]]
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(placed):,} of "
          f"{len(rows):,} firms placed ({100 * len(placed) / len(rows):.1f}%)",
          file=sys.stderr)
    if args.quiet:
        return
    from collections import Counter

    by_src = Counter(r["source_field"] for r in placed)
    print(f"  from place_listed {by_src['place_listed']:,}, "
          f"from head office {by_src['head_office_observed']:,}", file=sys.stderr)
    top = Counter(r["city"] for r in placed)
    print(f"  {len(top)} distinct cities; top:", file=sys.stderr)
    for city, n in top.most_common(12):
        print(f"    {n:5d}  {city}", file=sys.stderr)


if __name__ == "__main__":
    main()
