"""Validation suite for the pipeline and the built dataset.

Run after any change to the parsers, and after a full rebuild:

    python3 src/checks.py            # unit checks + dataset integrity
    python3 src/checks.py --unit     # parser checks only (no data needed)

The extraction check matters most. The source PDFs embed subsetted Type1
fonts with MacRoman encodings, and several PDF libraries decode them into a
monotonic substitution cipher instead of failing loudly: "Publie le 19
janvier" comes out as "«uelieHleHYeHjenvier". A silent switch of extraction
backend would therefore produce a dataset of plausible-looking garbage. The
check asserts that ordinary French words survive extraction.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import encode_url, plausible_year, split_title  # noqa: E402
from names import looks_like_org, org_key, parse_person_name  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC_DIR = os.path.join(ROOT, "data", "processed")

FAILURES: list[str] = []
CHECKS = {"passed": 0, "failed": 0}


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        CHECKS["passed"] += 1
    else:
        CHECKS["failed"] += 1
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")
        print(f"  FAIL  {label} {detail}", file=sys.stderr)


def eq(label: str, got, want) -> None:
    check(label, got == want, f"got {got!r}, want {want!r}")


# --- parser unit checks --------------------------------------------------
def check_names() -> None:
    print("names.parse_person_name", file=sys.stderr)
    cases = [
        # raw, given, surname
        ("Georges Despret", "Georges", "Despret"),
        ("A. R. Fontaine", "A. R.", "Fontaine"),
        ("J. de Margerie", "J.", "de Margerie"),
        ("Henry de Sieyès", "Henry", "de Sieyès"),
        ("André Laurent-Atthalin", "André", "Laurent-Atthalin"),
        ("Dr H.-A. Van Nierop", "H.-A.", "Van Nierop"),
        # A compound surname behind an honorific must not lose its first word.
        ("baron Carton de Wiart", "", "Carton de Wiart"),
        # Surname-first, with and without parentheses.
        ("PHILIPPAR (Edmond)", "Edmond", "Philippar"),
        ("Chabert Pierre", "Pierre", "Chabert"),
        # The sources expand an initial in place.
        ("P(aul) Delorme", "Paul", "Delorme"),
        ("L(éonard) Fontaine", "Léonard", "Fontaine"),
    ]
    for raw, given, surname in cases:
        p = parse_person_name(raw)
        eq(f"  {raw!r} given", p["given"], given)
        eq(f"  {raw!r} surname", p["surname"], surname)

    print("names.looks_like_org", file=sys.stderr)
    for raw in ["la Société centrale d'études", "la Banque privée", "Cie générale du Maroc",
                "Éts Xicoira", "Crédit foncier d'Algérie", "Les Cultures marocaines",
                "L'Alfa", "LA MANUTENTION MAROCAINE"]:
        check(f"  org {raw!r}", looks_like_org(raw))
    for raw in ["Georges Despret", "A. R. Fontaine", "baron Carton de Wiart",
                # Prose fragments starting with an article must not be filed as
                # companies; the article rule is case-sensitive for that reason.
                "Les travaux comme", "la description qui"]:
        check(f"  not an org {raw!r}", not looks_like_org(raw))

    print("names.org_key", file=sys.stderr)
    same = [
        ("Compagnie des Chemins de fer du Maroc", "Cie des chemins de fer du Maroc"),
        ("Omnium nord-africain", "Omnium nord-africain (Anct Bonnaud et Cie)"),
        ("Société Africaine de Distilleries", "Africaine de distilleries"),
    ]
    for a, b in same:
        eq(f"  {a[:32]!r} == {b[:32]!r}", org_key(a), org_key(b))
    check("  distinct firms stay distinct",
          org_key("Banque de l'Algérie") != org_key("Banque d'État du Maroc"))


def check_urls() -> None:
    """Non-ASCII PDF filenames must be percent-encoded before the request.

    Many filenames on the site contain characters that are legal in a filename
    but not in an HTTP request line. Passing them through raw raises
    UnicodeEncodeError inside urllib, which is indistinguishable from a dead
    link in the extraction log; 32 documents were lost to this before it was
    caught. The encoded URL must also be pure ASCII, or the same error recurs.
    """
    print("common.encode_url", file=sys.stderr)
    cases = [
        ("https://entreprises-coloniales.fr/afrique-du-nord/Banque_Cox_&_C°-Algerie.pdf",
         "https://entreprises-coloniales.fr/afrique-du-nord/Banque_Cox_&_C%C2%B0-Algerie.pdf"),
        ("https://entreprises-coloniales.fr/inde-indochine/Amis_de_l_art_Saïgon_1935.pdf",
         "https://entreprises-coloniales.fr/inde-indochine/Amis_de_l_art_Sa%C3%AFgon_1935.pdf"),
    ]
    for raw, want in cases:
        eq(f"  encodes {raw[-34:]!r}", encode_url(raw), want)
    for raw, _ in cases:
        got = encode_url(raw)
        check(f"  ascii-safe {raw[-28:]!r}", got.isascii(), got)
    # An already-encoded or plain-ASCII URL must pass through unchanged.
    for raw in [
        "https://entreprises-coloniales.fr/empire/Colonial_Trust.pdf",
        "https://entreprises-coloniales.fr/afrique-du-nord/Banque_Cox_&_C%C2%B0-Algerie.pdf",
    ]:
        eq(f"  idempotent {raw[-30:]!r}", encode_url(raw), raw)


def check_titles() -> None:
    print("common.split_title", file=sys.stderr)
    p = split_title("Abattoirs municipaux et industriels au Maroc (Société générale des), Casablanca : une")
    eq("  head un-inverted", p["name_normalised"],
       "Société générale des Abattoirs municipaux et industriels au Maroc")
    eq("  place split off", p["place_listed"], "Casablanca")

    p = split_title("Africaine de Mines (Société)(1900-1903) : mines de l'Ouenza")
    eq("  operating period start", p["year_start"], "1900")
    eq("  operating period end", p["year_end"], "1903")
    check("  generic head is not a forename", not p["first_paren_is_forename"])

    p = split_title("Jourdan (Adolphe)(1846-1916), Alger : imprimeur")
    check("  forename detected", p["first_paren_is_forename"])
    eq("  place", p["place_listed"], "Alger")

    p = split_title("Agricole, Financière Industrielle et Minière de l'Indochine (Société)(Safimic), Hanoï")
    eq("  alias captured", p["alias"], "Safimic")
    eq("  place", p["place_listed"], "Hanoï")


def check_citations() -> None:
    import parse_ties as P

    print("parse_ties.CITATION_RE", file=sys.stderr)
    should_match = [
        ("(La Journée industrielle, 22 mars 1927)", "1927"),
        ("(Les Annales coloniales, 10 août 1921)", "1921"),
        ("(La Cote de la Bourse et de la banque, 26 décembre 1920)", "1920"),
        ("(Indochine, février-mars 1929)", "1929"),
        ("(Exposition coloniale internationale de Paris, 1931)", "1931"),
    ]
    for text, year in should_match:
        m = P.CITATION_RE.search(text)
        check(f"  matches {text[:44]!r}", bool(m))
        if m:
            eq(f"  year of {text[:34]!r}", m.group("year"), year)
            check(f"  not a history note {text[:34]!r}",
                  not P.HISTORY_NOTE_RE.search(m.group("body")))

    # Company-history notes must not be read as dated sources: doing so used to
    # date a whole run of boards to the firm's founding year.
    should_not = [
        "(Anciens Éts Salmon, fondés en 1818)",
        "(Ancienne maison P. Lemoine, fondée en 1867)",
        "(A pris la suite de la société Maurel frères, fondée en 1849)",
    ]
    for text in should_not:
        m = P.CITATION_RE.search(text)
        rejected = (m is None) or bool(P.HISTORY_NOTE_RE.search(m.group("body")))
        check(f"  rejects history note {text[:44]!r}", rejected)

    print("parse_ties board lists", file=sys.stderr)
    body = ("MM. Georges Despret, présid. ; Wladimir Archawski, admin.-dél. ; "
            "Mathieu Angelini, Victor Berti, Paul Eonnet, administrateurs.")
    check("  list recognised", P.looks_like_name_list(body))
    members = P.parse_board_list(body, "administrateur")
    names = [m["name_clean"] for m in members]
    roles = {m["name_clean"]: m["role"] for m in members}
    eq("  member count", len(members), 5)
    eq("  president identified", roles.get("Georges Despret"), "president")
    eq("  delegate identified", roles.get("Wladimir Archawski"), "administrateur_delegue")
    check("  plain administrator", roles.get("Victor Berti") == "administrateur", str(roles))

    # Narrative prose must not be mined for names.
    prose = ("est autorisé à émettre des obligations jusqu'à concurrence de 800.000 fr. "
             "Les statuts ont été modifiés en conséquence, sous la condition suspensive "
             "de la réalisation de cette augmentation.")
    check("  prose rejected as a list", not P.looks_like_name_list(prose))

    # PROSE_START_RE lists French function words that also open real names.
    # These are regression tests for both directions of that collision.
    for frag in ["A. R. Fontaine", "E. Mirabaud", "D'Aubigny", "Le Bris",
                 "La Fontaine", "Du Pasquier", "Des Rotours"]:
        check(f"  name-like {frag!r}", P._fragment_is_namelike(frag))
    for frag in ["a été décidé que", "la description qui", "des immeubles et",
                 "le conseil est autorisé", "Les travaux comme"]:
        check(f"  prose-like {frag!r}", not P._fragment_is_namelike(frag))

    # An initial-led name must survive the whole board-list path, not just the
    # fragment test: "A." collides with the French verb "a".
    body = "MM. A. R. Fontaine (Distill. Indoch.), présid.; P(aul) Delorme, admin."
    members = P.parse_board_list(body, "administrateur")
    names = {m["name_clean"] for m in members}
    check("  initial-led name kept", "A. R. Fontaine" in names, str(names))
    check("  in-place initial expanded", "Paul Delorme" in names, str(names))
    annots = {m["name_clean"]: m["annotation"] for m in members}
    eq("  annotation captured", annots.get("A. R. Fontaine"), "Distill. Indoch.")

    # Corporate directors are companies, not people.
    body = "MM. Charles Thévenet, président ; la Société centrale d'études, vice-président"
    members = P.parse_board_list(body, "administrateur")
    types = {m["name_clean"]: m["member_type"] for m in members}
    check("  corporate director typed as organisation",
          any(v == "organisation" for v in types.values()), str(types))

    print("common.plausible_year", file=sys.stderr)
    eq("  rejects 1677", plausible_year("1677"), "")
    eq("  accepts 1920", plausible_year("1920"), "1920")
    eq("  rejects empty", plausible_year(""), "")


def check_extraction() -> None:
    """Assert the PDF backend decodes the site's font encodings correctly."""
    print("PDF extraction backend", file=sys.stderr)
    import importlib.util

    check("  pymupdf importable", importlib.util.find_spec("pymupdf") is not None,
          "pip install pymupdf")
    if importlib.util.find_spec("pymupdf") is None:
        return

    import glob
    import gzip

    files = sorted(glob.glob(os.path.join(ROOT, "data", "text", "*.txt.gz")))
    if not files:
        print("  (no extracted text yet - skipping decode check)", file=sys.stderr)
        return
    sample = files[: min(40, len(files))]
    # Ordinary French function words. Under the cipher these come out as
    # "le" -> "lï", "de" -> "îï", "et" -> "ït", so their absence across dozens
    # of documents means the text layer was mis-decoded.
    probes = (" le ", " la ", " de ", " et ", " des ", " société", "capital")
    clean = 0
    for f in sample:
        t = gzip.open(f, "rt", encoding="utf-8").read().lower()
        if any(p in t for p in probes):
            clean += 1
    check("  French text decodes correctly",
          clean >= 0.8 * len(sample), f"{clean}/{len(sample)} documents contain French stopwords")
    # The cipher's signature: 'H' standing in for the space character.
    ciphered = 0
    for f in sample:
        t = gzip.open(f, "rt", encoding="utf-8").read()
        if re.search(r"[a-zé]H[a-zé]{2,}H[a-zé]{2,}H", t):
            ciphered += 1
    check("  no substitution-cipher signature", ciphered == 0, f"{ciphered} documents look ciphered")


# --- dataset integrity --------------------------------------------------
def load(name: str) -> list[dict]:
    path = os.path.join(PROC_DIR, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def check_dataset() -> None:
    print("dataset integrity", file=sys.stderr)
    docs = load("documents.csv")
    check("  documents.csv present", bool(docs))
    if not docs:
        return
    ids = [r["doc_id"] for r in docs]
    eq("  doc_id unique", len(set(ids)), len(ids))
    check("  every document has a URL", all(r["pdf_url"].startswith("http") for r in docs))

    companies = load("companies.csv")
    persons = load("persons_resolved.csv")
    edges = load("edges_person_company.csv")
    if not (companies and persons and edges):
        print("  (network not built yet - skipping edge checks)", file=sys.stderr)
        return

    cids = {r["company_id"] for r in companies}
    pids = {r["person_id"] for r in persons}
    eq("  company_id unique", len(cids), len(companies))
    eq("  person_id unique", len(pids), len(persons))

    dangling_c = {e["company_id"] for e in edges} - cids
    dangling_p = {e["person_id"] for e in edges} - pids
    eq("  no dangling company references", len(dangling_c), 0)
    eq("  no dangling person references", len(dangling_p), 0)

    check("  no empty endpoints",
          all(e["company_id"] and e["person_id"] for e in edges))

    bad_years = [e["year"] for e in edges if e["year"] and not plausible_year(e["year"])]
    eq("  all edge years plausible", len(bad_years), 0)

    dated = sum(1 for e in edges if e["year"])
    check("  most edges are dated", dated >= 0.9 * len(edges),
          f"{dated}/{len(edges)}")

    # An implausibly long career signals two namesakes merged into one node.
    long_span = 0
    for r in persons:
        if r["first_year"] and r["last_year"]:
            if int(r["last_year"]) - int(r["first_year"]) > 70:
                long_span += 1
    check("  few implausible career spans", long_span <= 0.01 * len(persons),
          f"{long_span}/{len(persons)} exceed 70 years")

    # Control characters from the PDF text layer must not reach the outputs.
    # NUL is legal in a CSV cell but illegal in XML even when escaped, so one
    # leaking through produced a GraphML file that no parser would load.
    import glob as _glob

    illegal = bytes(range(0, 9)) + bytes([11, 12]) + bytes(range(14, 32))
    dirty = []
    for path in sorted(_glob.glob(os.path.join(PROC_DIR, "*.csv"))):
        raw = open(path, "rb").read()
        if any(bytes([c]) in raw for c in illegal):
            dirty.append(os.path.basename(path))
    check("  no control characters in any CSV", not dirty, "; ".join(dirty))

    for path in sorted(_glob.glob(os.path.join(ROOT, "data", "graphs", "*.graphml"))):
        try:
            import xml.etree.ElementTree as ET

            ET.parse(path)
            check(f"  {os.path.basename(path)} is well-formed XML", True)
        except Exception as exc:  # noqa: BLE001
            check(f"  {os.path.basename(path)} is well-formed XML", False, str(exc)[:120])

    # Territory labelling. Pages covering several territories mark only the
    # first with premierTitrePays and the rest with titrePays; handling only
    # the former put all 189 Madagascar documents under "Djibouti".
    countries = Counter(d["country"] for d in docs if d["country"])
    for expected in ["Madagascar", "La Réunion", "Comores", "Guyane française",
                     "Tahiti (Polynésie)", "Nouvelles-Hébrides (Mélanésie)"]:
        check(f"  territory {expected!r} is populated", countries.get(expected, 0) > 0,
              f"{countries.get(expected, 0)} documents")
    check("  Madagascar outnumbers Djibouti", countries.get("Madagascar", 0) >
          countries.get("Djibouti", 0),
          f"Madagascar={countries.get('Madagascar', 0)}, Djibouti={countries.get('Djibouti', 0)}")

    # Multi-firm surveys must not become company nodes: treated as firms, they
    # absorb every board they list and dominate the degree distribution.
    firms = {r["name"]: r for r in companies}
    for title in ["Documentation africaine", "Parlementaires et financiers",
                  "Sociétés aurifères en Côte-d'Ivoire", "Leroy, Le Caoutchouc",
                  "Valeurs inscrites à la Cote des banquiers à Paris en 1913"]:
        check(f"  survey not a company node: {title[:44]!r}", title not in firms)
    # No firm should have an implausible number of distinct directors. The
    # genuine maximum here is ~96 (Cie Generale Francaise de Tramways, observed
    # 1880-1960); the pseudo-firms reached 254 and 286.
    worst = max(companies, key=lambda r: int(r["n_directors"] or 0), default=None)
    if worst:
        check("  no firm has an implausible director count",
              int(worst["n_directors"]) <= 150,
              f"{worst['name'][:50]!r} has {worst['n_directors']}")

    il = load("edges_company_interlock.csv")
    if il:
        check("  interlock endpoints known",
              all(e["company_id_1"] in cids and e["company_id_2"] in cids for e in il))
        check("  no interlock self-loops",
              all(e["company_id_1"] != e["company_id_2"] for e in il))


def check_splits() -> None:
    """The per-territory bundles must partition ties and stay loadable."""
    import glob as _glob

    for level in ("country", "region"):
        root = os.path.join(ROOT, "data", f"by_{level}")
        manifest_path = os.path.join(root, "territory_manifest.csv")
        if not os.path.exists(manifest_path):
            continue
        print(f"split by {level}", file=sys.stderr)
        with open(manifest_path, encoding="utf-8", newline="") as fh:
            manifest = list(csv.DictReader(fh))
        check(f"  {level}: manifest is non-empty", bool(manifest))

        # Ties carry exactly one territory, so the bundles must partition them
        # exactly - no tie duplicated into two bundles, none dropped.
        bundle_ties = 0
        for f in _glob.glob(os.path.join(root, "*", "affiliations.csv")):
            with open(f, encoding="utf-8", newline="") as fh:
                bundle_ties += sum(1 for _ in csv.DictReader(fh))
        total = sum(int(r["n_ties"]) for r in manifest)
        eq(f"  {level}: bundle files match manifest tie counts", bundle_ties, total)

        aff = load("affiliations.csv")
        attributed = sum(1 for r in aff if r["company_key"] and r["person_key"])
        eq(f"  {level}: ties partition the dataset", total, attributed)

        # Every bundle's GraphML must load, same guard as the main graphs.
        bad = []
        for f in _glob.glob(os.path.join(root, "*", "company_interlock.graphml")):
            try:
                import xml.etree.ElementTree as ET

                ET.parse(f)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{os.path.basename(os.path.dirname(f))}: {exc}")
        check(f"  {level}: all bundle graphs are well-formed", not bad, "; ".join(bad[:3]))

        # A bundle must only contain ties from its own territory.
        field = "country" if level == "country" else "region"
        leaks = []
        for f in _glob.glob(os.path.join(root, "*", "affiliations.csv")):
            slug = os.path.basename(os.path.dirname(f))
            with open(f, encoding="utf-8", newline="") as fh:
                vals = {r[field] for r in csv.DictReader(fh)}
            if len(vals) > 1:
                leaks.append(f"{slug}: {sorted(vals)[:3]}")
        check(f"  {level}: no bundle mixes territories", not leaks, "; ".join(leaks[:3]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", action="store_true", help="parser checks only")
    args = ap.parse_args()

    check_names()
    check_urls()
    check_titles()
    check_citations()
    if not args.unit:
        check_extraction()
        check_dataset()
        check_splits()

    total = CHECKS["passed"] + CHECKS["failed"]
    print(f"\n{CHECKS['passed']}/{total} checks passed", file=sys.stderr)
    if FAILURES:
        print("\nfailures:", file=sys.stderr)
        for f in FAILURES:
            print(f"  - {f}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
