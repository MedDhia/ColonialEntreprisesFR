"""Group the source's 109 sector labels into an analysable vocabulary.

    python3 src/sectors.py --sync     # regenerate data/reference/sector_groups.csv
    python3 src/sectors.py --report   # labels with no group, and the group sizes

`companies.csv`'s `sectors` column is the site's own filing vocabulary, taken
as printed. It cannot be cross-tabulated as it stands, for three reasons, and
this module fixes all three while keeping the raw label in every output row.

**1. The modal value is not a sector.** `Documents généraux (par ordre
chronologique)` covers 5,397 firms — it is the chronological document dump the
compiler files press clippings under. With `Documents généraux`,
`Documentation générale` and their variants it accounts for most of the
catalogue. **2,941 of the 6,454 firms with a board carry no other sector at
all**, so any sector cross-tab is computed on 3,513 firms and must say so.

**2. The field carries site chrome.** Among the 109 labels are `Alain LÉGER,
créateur du site …, a publié`, `Pour une utilisation optimale de nos liens,
téléchargez nos pdf`, `Messages personnels` and `documents`. These are
navigation text that landed in a heading slot. They are mapped to
`not_a_sector` and excluded, not silently counted.

**3. One sector is spelled five ways.** Six labels are mining (`Mines`, `Mines
et carrières`, `Groupes miniers transcoloniaux`, `Mines et métallurgie`, `Mines
et placers`, `mines et industries`); six are banking; five are agri-food, one
of them differing from another only in case (`industries agro-alimentaires`).
Tabulating the raw labels splits every real sector into fragments and puts none
of them near the top.

Two residual groups, deliberately distinct:

- `unclassified` — the *source's own* residual buckets: `Divers`, `Industries
  diverses`, `Sociétés`, `Industrie`. A firm here really is filed under an
  economic residual, which is information; it is kept and reported separately.
- `not_a_sector` — filing categories and site chrome. No economic content.
  Excluded from every rate.

**The mapping lives in `data/reference/sector_groups.csv`, not in this file.**
The patterns below regenerate it with `--sync`, but read time uses the CSV, so
a hand edit to the CSV wins and survives the next sync of unrelated labels.
`checks.py` asserts every label in `companies.csv` appears in it.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
REF = os.path.join(ROOT, "data", "reference")
MAP_PATH = os.path.join(REF, "sector_groups.csv")

# Ordered most specific first; the first pattern that matches a label wins.
# Every group carries an English label, used by the figures.
RULES: list[tuple[str, str, str]] = [
    # --- not a sector at all: filing categories and site chrome ----------
    ("not_a_sector", "Not a sector",
     r"documents?\s+g[eé]n[eé]raux|documentation\s+g[eé]n[eé]rale|"
     r"^documents?$|^g[eé]n[eé]ralit[eé]s$|messages\s+personnels|"
     r"alain\s+l[eé]ger|utilisation\s+optimale|collections\s+d['’]anciens|"
     r"amiti[eé]\s+et\s+solidarit[eé]|amicales\s+r[eé]gionales|"
     r"organismes\s+repr[eé]sentatifs|syst[eè]me\s+mon[eé]taire"),
    # --- the source's own residual buckets ------------------------------
    ("unclassified", "Unclassified",
     r"^industries?\s+diverses?$|^industries?$|^soci[eé]t[eé]s?$|"
     r"^soci[eé]t[eé]s\s+diverses?$|^divers$|^autres\s+soci[eé]t[eé]s$|"
     r"^entreprises\s+diverses$|^soci[eé]t[eé]s\s+fran[cç]aises"),
    # --- real sectors ----------------------------------------------------
    ("mining", "Mining and quarrying",
     r"\bmines?\b|\bminiers?\b|\bplacers\b|p[eé]trole|carri[eè]res"),
    ("finance", "Banking, finance and insurance",
     r"banques?\b|financi[eè]re?s?\b|assurance|assureurs|scripophilie"),
    ("plantations", "Plantations and commodity crops",
     r"h[eé]v[eé]as|caoutchouc|caf[eé]|[eé]pices|plantations|rizi[eè]res|"
     r"^agriculture$|hydraulique\s+agricole"),
    ("food_processing", "Food processing, livestock and fishing",
     r"agro-alimentaire|industries?\s+alimentaires?|[eé]levage|abattage|"
     r"p[eê]che"),
    ("transport", "Transport, ports and docks",
     r"transports?\b|ports\b|phares|docks"),
    ("trade", "Trade and commerce",
     r"^commerce$|soci[eé]t[eé]s\s+commerciales|engagistes|"
     r"recruteurs\s+de\s+main"),
    ("construction", "Construction and building materials",
     r"b[aâ]timent|travaux\s+publics|c[eé]ramiques?"),
    ("utilities", "Water, gas and electricity",
     r"eaux?\b.*[eé]lectricit|[eé]lectricit.*eaux?\b|utilities|"
     r"assainissement|\bgaz\b"),
    ("metals_engineering", "Metallurgy and engineering",
     r"m[eé]tallurgie|constructions\s+(?:m[eé]caniques|navales)"),
    ("wood_paper", "Wood, furniture and paper",
     r"\bbois\b|meubles|papier|cellulose|li[eè]ge|allumettes|fili[eè]re\s+bois"),
    ("textiles_leather", "Textiles and leather",
     r"cuirs?\b|textiles?\b|filatures"),
    ("chemicals", "Chemicals and pharmaceuticals",
     r"chimiques?|pharmaceutiques|parachimie"),
    ("real_estate", "Land and real estate",
     r"fonci[eè]re?s?\b|immobili"),
    ("hospitality", "Hotels and tourism", r"h[oô]tellerie|tourisme"),
    ("media_print", "Press, printing and communications",
     r"imprimerie|presse|[eé]dition|t[eé]l[eé]graphe|t[eé]l[eé]phone|radio|"
     r"cin[eé]mas?|th[eé][aâ]tres?"),
    ("health_education", "Health, education and research",
     r"^sant[eé]$|enseignement|recherche|soci[eé]t[eé]s\s+savantes|mus[eé]es"),
    ("culture_leisure", "Culture, sport and leisure",
     r"^sports?$|artistes|galeries|loisirs|religieuses"),
    ("conglomerate", "Transcolonial and diversified groups",
     r"groupes?\s+(?:industriels|indochinois)|dirigeants\s+d['’]affaires"),
]

_COMPILED = [(g, en, re.compile(p, re.I)) for g, en, p in RULES]

# Groups with no economic content, excluded from every rate the figures draw.
EXCLUDED = {"not_a_sector"}


def classify(label: str) -> tuple[str, str]:
    """`(group, group_en)` for one raw label, by the first matching rule."""
    for group, english, rx in _COMPILED:
        if rx.search(label):
            return group, english
    return "unmapped", "Unmapped"


def load_map() -> dict[str, tuple[str, str]]:
    """The committed mapping. This, not `classify`, is what callers read."""
    out: dict[str, tuple[str, str]] = {}
    if not os.path.exists(MAP_PATH):
        return out
    with open(MAP_PATH, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["raw"]] = (row["group"], row["group_en"])
    return out


def raw_labels() -> collections.Counter:
    path = os.path.join(PROC, "companies.csv")
    c: collections.Counter = collections.Counter()
    if not os.path.exists(path):
        return c
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            for s in (row.get("sectors") or "").split("; "):
                s = s.strip()
                if s:
                    c[s] += 1
    return c


def sector_of(record: dict, mapping=None) -> tuple[str, str, str]:
    """`(group, group_en, raw)` for one company record.

    The **first non-excluded** sector wins, not the first listed: a firm whose
    first label is `Documents généraux` and whose second is `Mines` is a mining
    firm, and taking the first listed would have filed it under a document
    dump. Returns `("not_a_sector", …)` only when every label is excluded.
    """
    mapping = mapping if mapping is not None else load_map()
    labels = [s.strip() for s in (record.get("sectors") or "").split("; ")
              if s.strip()]
    fallback = ("not_a_sector", "Not a sector", labels[0] if labels else "")
    for label in labels:
        group, english = mapping.get(label) or classify(label)
        if group not in EXCLUDED:
            return group, english, label
    return fallback


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true",
                    help="write data/reference/sector_groups.csv")
    ap.add_argument("--report", action="store_true",
                    help="unmapped labels and group sizes")
    args = ap.parse_args()

    labels = raw_labels()
    existing = load_map()
    rows = []
    for label, n in sorted(labels.items(), key=lambda kv: (-kv[1], kv[0])):
        # A hand edit already in the CSV wins over the pattern table -
        # except `unmapped`, which is the absence of a decision rather than
        # one, and would otherwise make a single bad sync permanent.
        prior = existing.get(label)
        group, english = (prior if prior and prior[0] != "unmapped"
                          else classify(label))
        rows.append({"raw": label, "group": group, "group_en": english,
                     "n_companies": n})

    if args.sync:
        os.makedirs(REF, exist_ok=True)
        with open(MAP_PATH, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["raw", "group", "group_en",
                                              "n_companies"])
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {os.path.relpath(MAP_PATH, ROOT)}: {len(rows)} labels",
              file=sys.stderr)

    unmapped = [r for r in rows if r["group"] == "unmapped"]
    if unmapped or args.report:
        print(f"unmapped labels: {len(unmapped)}", file=sys.stderr)
        for r in unmapped:
            print(f"  {r['n_companies']:5}  {r['raw'][:70]}", file=sys.stderr)

    if args.report:
        sizes = collections.Counter()
        for r in rows:
            sizes[r["group"]] += r["n_companies"]
        print("\ngroup sizes (label occurrences, not firms):", file=sys.stderr)
        for g, n in sizes.most_common():
            mark = "  [excluded]" if g in EXCLUDED else ""
            print(f"  {n:6}  {g}{mark}", file=sys.stderr)

    if unmapped:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
