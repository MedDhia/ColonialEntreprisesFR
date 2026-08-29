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
import math
import os
import random
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

    print("parse_ties bracketed forenames and annotations", file=sys.stderr)
    # One board list from the Fedhala dossier that exercised four failures at
    # once: an annotation containing a comma, an annotation containing "et",
    # an in-place expanded initial, and a leading supplied forename.
    body = ("MM. J.-B. Hersent [ép. Anne-Marie Thomas, sœur de Georges], présid. ; "
            "G[eorges] Hersent, v.-présid. ; "
            "A[nthony] Kroller [Wm. H. Müller et Cie, Rotterdam ], "
            "[Charles] Michel-Côte, sir John Pilter [Phosphates Océanie]")
    got = [m["name_clean"] for m in P.parse_board_list(body, "administrateur")]
    for want in ["Georges Hersent", "Anthony Kroller", "Charles Michel-Côte"]:
        check(f"  forename recovered: {want!r}", want in got, str(got))
    # The comma inside "[... et Cie, Rotterdam]" used to split the annotation in
    # two and leave "Rotterdam ]" as a board member.
    check("  no annotation residue parsed as a person",
          not any("]" in n or "[" in n for n in got), str(got))
    check("  kinship note did not enter the surname",
          not any("Anne-Marie" in n for n in got), str(got))

    # The guard on the leading form: only an attested forename folds in.
    for frag, want in [("E[ugène] Hausermann [ECP][Hersent]", "Eugène Hausermann"),
                       ("[Charles] Michel-Côte", "Charles Michel-Côte")]:
        m = P._make_member(frag, "administrateur")
        eq(f"  {frag[:26]!r} parsed", m and m["name_clean"], want)
    m = P._make_member("[Phosphates] Océanie", "administrateur")
    check("  a non-forename bracket is not folded in",
          not m or "Phosphates" not in m["name_clean"], str(m))

    print("parse_ties entry anchors", file=sys.stderr)
    # The Annuaire industriel alphabetises on a keyword and parenthesises the
    # rest of the name. Reading the head whole, and putting it back in the right
    # order, is what keeps one notice from collecting the next one's board.
    heads = [
        ("ALLUMETTES (Soc. indo-chinoise forestière et des), 41, bd de Magenta,",
         "Soc. indo-chinoise forestière et des ALLUMETTES"),
        # No parenthetical, two particles between the capitals. This is the case
        # CAPS_ENTRY_RE could not see, and its board went to the notice above.
        ("BANQUE de l'INDOCHINE, 96, bd Haussmann, Paris, 8e. T. Europe 48-00",
         "BANQUE de l'INDOCHINE"),
        # The keyword itself contains commas; cutting at the first one named
        # this firm "Forges".
        ("FORGES, ATELIERS et CHANTIERS d'INDOCHINE, Bureau : 119, bd Haussmann,",
         "FORGES, ATELIERS et CHANTIERS d'INDOCHINE"),
        ("CULTURES TROPICALES (Soc. Indochinoise des), 51. r. d'Anjou, Paris, 8e.",
         "Soc. Indochinoise des CULTURES TROPICALES"),
        ("AGRICOLE de THANH-TUY-HA (Société). 53, cours Pierre-Puget, Marseille",
         "Société AGRICOLE de THANH-TUY-HA"),
        # A parenthetical ending in an apostrophe joins with no space.
        ("ACCONAGE (Soc. Nord-Africaine d'), Alger.",
         "Soc. Nord-Africaine d'ACCONAGE"),
    ]
    for text, want in heads:
        m = P.ANNUAIRE_INDUS_ENTRY_RE.match(text)
        check(f"  head matches {text[:34]!r}", bool(m))
        if m:
            eq(f"  head rebuilt {text[:26]!r}",
               P.annuaire_indus_name(m.group("kw"), m.group("paren")), want)

    # All three ways the compiler writes an AEC page reference. Only the first
    # was matched, so 17 entries across 11 documents anchored nowhere.
    for text in ("AEC 1922-519 - Sté générale des abattoirs, PARIS",
                 "AEC 1922. — 489 — Cie du port de Fedhala, 60, rue de Londres",
                 "AEC 1922. 495 — Manufacture marocaine de calorifuges"):
        check(f"  AEC entry matches {text[:26]!r}", bool(P.AEC_RE.search(text)))

    # Once the listing is running the prefix is dropped and only the page is
    # printed. Three digits, because the annuaire runs to 800-1,200 pages and
    # the short numbers are enumerated clauses in legal prose.
    for text in ("509 — Sté des briqueteries de Fedhala, 60, rue de Londres",
                 "35 [= 64] — Sté d'études marocaines pour le commerce"):
        check(f"  bare page matches {text[:28]!r}",
              bool(P.AEC_BARE_PAGE_RE.search(text)))
    for text in ("3 — Modifications diverses aux articles 4, 8 12, 13, 15",
                 "5 — Que l'imprimeur a estimé que l'auteur, en tant que",
                 "1877-Démissionnaire le 16 mai 1877.",
                 "1894-Sainte-Adresse, Seine-Inférieure, 1919), fille d'un"):
        check(f"  bare page rejects {text[:28]!r}",
              not P.AEC_BARE_PAGE_RE.search(text))

    # A bare page takes the year of the nearest AEC entry *before* it. Taking
    # the document's first stamped the Fedhala dossier's two 1951 entries as
    # 1922 - a 29-year error on four board seats.
    two_volume = ("AEC 1922. — 489 — Cie du port de Fedhala, rue de Londres\n"
                  "509 — Sté des briqueteries de Fedhala, rue de Londres\n"
                  "AEC 1951. — 819 — Cie du port de Fédala (C.P.F), rue de Liège\n"
                  "826 — Les Conserveries marocaines (COSMAR)\n")
    years = {a.company: a.year for a in P.find_anchors(two_volume, False)
             if a.kind == "aec_entry"}
    eq("  bare page before the 1951 entry keeps 1922",
       years.get("Sté des briqueteries de Fedhala"), "1922")
    eq("  bare page after the 1951 entry takes 1951",
       years.get("Les Conserveries marocaines (COSMAR)")
       or years.get("Les Conserveries marocaines"), "1951")

    # Both head patterns must report the same offset for the same notice, or
    # the anchor de-duplication below them silently does nothing.
    head = "ALLUMETTES (Soc. indo-chinoise forestière et des), 41, bd de Magenta,\n"
    doc = "x\n" + head
    caps = [m.start() for m in P.CAPS_ENTRY_RE.finditer(doc)]
    ind = [m.start() for m in P.ANNUAIRE_INDUS_ENTRY_RE.finditer(doc)]
    check("  caps and industriel heads agree on the offset",
          bool(caps) and bool(ind) and caps[0] == ind[0], f"{caps} vs {ind}")

    print("parse_ties swallowed role labels", file=sys.stderr)
    # The label states the role of the name behind it and overrides the role
    # inherited from the enclosing list. Discarding it filed 199 "Adm.:" rows
    # as president and 113 "Prés.:" rows as administrateur.
    for frag, name, role in [
            ("Adm.: MM. Henri Girche", "Henri Girche", "administrateur"),
            ("Prés.: M. J. Garcin", "J. Garcin", "president"),
            ("Prés:. M. J. Garcin", "J. Garcin", "president"),
            ("Adm.-dél.: M. Jean Dupont", "Jean Dupont", "administrateur_delegue"),
            ("direct. gén.: M. Léon Blum", "Léon Blum", "directeur_general"),
            ("Censeurs: MM. Paul Reynaud", "Paul Reynaud", "censeur"),
            ("administrateur-délégué: M. René Cassin", "René Cassin",
             "administrateur_delegue")]:
        m = P._make_member(frag, "administrateur")
        eq(f"  {frag[:26]!r} name", m and m["name_clean"], name)
        eq(f"  {frag[:26]!r} role", m and m["role"], role)
    # "pres." is the president; bare "pres" is the preposition "pres de".
    for text in ("près de Paris", "à près de 3 millions", "situé près du port"):
        eq(f"  {text!r} is not a role", P.canonical_role(text), "")

    print("parse_ties member labels", file=sys.stderr)
    # A swallowed role label hides a real name; strip it rather than lose the
    # tie. What is left after the strip must contain no colon.
    for text, want in [("Adm.: MM. Henri Girche", "Henri Girche"),
                       ("prés.:M. J. Bardoux", "J. Bardoux"),
                       ("Prés:. M. J. Garcin", "J. Garcin"),
                       ("Direct.: M. Patrick O'Quin", "Patrick O'Quin"),
                       ("Fondé de pouvoirs: Marcel Pénicaud", "Marcel Pénicaud")]:
        got = P.MEMBER_LABEL_PREFIX_RE.sub("", text)
        from names import LEADING_MM_RE

        got = LEADING_MM_RE.sub("", got).strip(" .,;:")
        eq(f"  label stripped from {text[:24]!r}", got, want)
    for text in ("comptoirs: Bordeaux", "Imp.: sucre",
                 "personnalités bien connues: Joanny Peytel"):
        got = P.MEMBER_LABEL_PREFIX_RE.sub("", text)
        check(f"  field value still rejected {text[:24]!r}", ":" in got)
    # An ordinary name must survive both rules untouched.
    for text in ("Pierre Barris", "Ed. Bousquet", "A. R. Fontaine"):
        eq(f"  name untouched {text!r}", P.MEMBER_LABEL_PREFIX_RE.sub("", text), text)

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
    # No firm should have an implausible number of distinct directors.
    #
    # The ceiling is recalibrated: it was 120, set when the dataset had one
    # extraction genre and 77% attribution, and the genuine maximum was ~96.
    # With four genres and 87% attribution the largest legitimate firms now
    # reach 186 (Banque de l'Indochine, observed across 61 distinct years
    # 1875-1971, about three directors a year), followed by Crédit foncier
    # colonial at 156 and Messageries maritimes at 142 - all of them the
    # longest-lived and best-documented firms in the collection. The failure
    # this guards against is a *pseudo-firm*: a survey document treated as a
    # company node, which reached 254 and 286. 240 sits between the two.
    worst = max(companies, key=lambda r: int(r["n_directors"] or 0), default=None)
    if worst:
        check("  no firm has an implausible director count",
              int(worst["n_directors"]) <= 240,
              f"{worst['name'][:50]!r} has {worst['n_directors']}")

    # A pseudo-firm absorbs a whole survey at once, so the sharper test is
    # directors in a *single* firm-year: a real board, even a large founding
    # list, does not run to hundreds.
    #
    # This ceiling was 200, chosen when the observed maximum was 83 (Compagnie
    # du Port de Fedhala, 1921) and read as a possible constitution list. It was
    # not: the Fedhala dossier reprints AEC entries for a dozen *other* firms
    # under shorthand heads that no anchor matched, so one firm collected a
    # dozen boards. With those heads anchored the dossier parser's own maximum
    # is 52; the merged network still reaches 82, on a pseudo-firm the annuaire
    # key names as several undertakings at once ("Houilleres du bassin de la
    # Loire + Houilleres des Cevennes..."). The ceiling is 90, so the headroom
    # is 8, not 38. Loosening it should mean a real large board was found, not
    # a re-run of either bug.
    per_year: Counter = Counter()
    for e in load("edges_person_company.csv"):
        if e["is_board_seat"] == "1" and e["year"]:
            per_year[(e["company_id"], e["year"])] += 1
    if per_year:
        (cid, yr), n = per_year.most_common(1)[0]
        check("  no firm-year has an implausible director count", n <= 90,
              f"{cid} in {yr} has {n}")

    # No person's name contains a colon, in *any* genre. The recoverable ones
    # ("Adm.: MM. Henri Girche") are stripped back to the name and the rest
    # rejected. Scanning only affiliations.csv missed 20 rows in the person
    # index and 6 resolved surnames, which came from a different parser.
    colon = []
    for f in ("affiliations.csv", "affiliations_person_index.csv",
              "affiliations_prose.csv", "affiliations_annotations.csv",
              "affiliations_biographical.csv", "persons_resolved.csv"):
        for r in load(f):
            for col in ("name_clean", "surname"):
                if ":" in (r.get(col) or ""):
                    colon.append((f, r[col]))
    check("  no member name carries a field label", not colon,
          f"{len(colon)} do, e.g. {colon[0][0]} {colon[0][1][:34]!r}" if colon else "")

    # Annotation residue in a name means a bracketed note was split across a
    # comma or an "et" again. It was 1,367 rows before the split learned to
    # protect them; the remainder are unbalanced brackets in the source itself.
    aff = load("affiliations.csv")
    residue = [a for a in aff if "[" in a["name_clean"] or "]" in a["name_clean"]]
    check("  little annotation residue in names", len(residue) <= 400,
          f"{len(residue)} rows, e.g. {residue[0]['name_clean'][:40]!r}" if residue else "")

    # The compiler supplies forenames in brackets. If this drops sharply, the
    # bracket conventions have stopped being read and the person splitter loses
    # the evidence it works from.
    full = sum(1 for a in aff if len(a["given"].replace(".", "").strip()) > 2)
    check("  full forenames recovered on a large share of ties",
          full >= 0.40 * len(aff), f"{full} of {len(aff)}")

    # Person resolution runs in both directions, and both must stay visible in
    # the crosswalk: folding merges, splitting separates.
    res = load("person_resolution.csv")
    rules = Counter(r["rule"] for r in res)
    check("  crosswalk records folds", rules["folded_unique_initial"] > 0, str(dict(rules)))
    check("  crosswalk records splits",
          rules["split_incompatible_forenames"] > 0, str(dict(rules)))
    split_rows = [r for r in res if r["rule"] == "split_incompatible_forenames"]
    check("  every split names the forenames it separated",
          all(r["split_forenames"] for r in split_rows))
    # A split key must yield distinct nodes, and the initial-only residue must
    # remain its own node rather than being handed to either man.
    pid = {p["person_id"] for p in load("persons_resolved.csv")}
    for stem, a, b in [("hersent-g", "georges", "gilbert"),
                       ("delmas-p", "philippe", "pierre")]:
        check(f"  {stem} split into {a} and {b}",
              f"{stem}-{a}" in pid and f"{stem}-{b}" in pid)
        check(f"  {stem} keeps an unresolved residue node", stem in pid)

    il = load("edges_company_interlock.csv")
    if il:
        check("  interlock endpoints known",
              all(e["company_id_1"] in cids and e["company_id_2"] in cids for e in il))
        check("  no interlock self-loops",
              all(e["company_id_1"] != e["company_id_2"] for e in il))


def check_positionality() -> None:
    """Guards on the onomastic coding, all of them lessons from its own output."""
    rows = load("person_positionality.csv")
    if not rows:
        return
    print("positionality coding", file=sys.stderr)
    import code_positionality as CP

    # Patterns that look right and are not. Each of these was measured against
    # the full name list and rejected; see data/reference/positionality_rules.md.
    for name, regions in [("Le Play", "Indochine"), ("Le Bret", "Indochine"),
                          ("Van Nierop", "Indochine"), ("Van Brée", "Indochine")]:
        pos, grp, _, _ = CP.code_person(name, regions, "")
        eq(f"  {name!r} is not Vietnamese", grp, "european_unspecified")
    for name in ["Rastoin", "Rabeau", "Raty", "Rabut", "Raymond du Boullay", "André Hermil"]:
        pos, grp, _, _ = CP.code_person(name, "Madagascar et Djibouti", "Madagascar")
        eq(f"  {name!r} is not Malagasy", grp, "european_unspecified")
    # An Ottoman rank was granted to Europeans in Egyptian service.
    for name in ["Boinet Bey", "H. Naus bey", "Ch. Audebeau bey"]:
        pos, grp, _, _ = CP.code_person(name, "Proche-Orient", "Égypte")
        eq(f"  {name!r} is not coded native on its title", pos, "colonial")

    # Names the coder must catch, including ones only reachable after recovery.
    for raw, want in [("Nguyen Van Vinh", "vietnamese"),
                      ("S. Exc. Hadj Thami Glaoui", "maghrebi_arab_berber"),
                      ("œufs. Meknès. David A. Benchimol", "maghrebi_jewish"),
                      ("Blaise Diagne", "west_african")]:
        n = CP.recover_name(raw)
        check(f"  {raw[:34]!r} survives the quality gate", CP.name_is_usable(n), n)
        _, grp, _, _ = CP.code_person(n, "Maroc; Indochine; Afrique occidentale francaise", "")
        eq(f"  {raw[:30]!r} group", grp, want)

    # Egypt and the Ottoman Empire were not French colonies.
    ott = [r for r in rows if r["positionality_group"] == "ottoman_egyptian"]
    check("  ottoman/egyptian names are not coded native",
          all(r["positionality"] == "local_non_french_elite" for r in ott),
          f"{sum(1 for r in ott if r['positionality'] == 'native')} coded native")
    # Maghrebi Jewish names are intermediate by construction, never native.
    jw = [r for r in rows if r["positionality_group"] == "maghrebi_jewish"]
    check("  maghrebi jewish names are intermediate",
          all(r["positionality"] == "intermediate" for r in jw))

    vals = {r["positionality"] for r in rows}
    check("  only documented positionality values",
          vals <= {"colonial", "native", "intermediate", "local_non_french_elite",
                   "unclassified"}, str(vals))


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

        # The bundles promise person ids that match the top-level files. They
        # did not for a while: this stage recomputed the resolution over
        # `affiliations.csv` alone while stage 4 resolved over all five genres,
        # so a fold or a split could differ. It now reads stage 4's crosswalk.
        top = {p["person_id"] for p in load("persons_resolved.csv")}
        stray = set()
        for f in sorted(_glob.glob(os.path.join(root, "*", "persons.csv")))[:80]:
            with open(f, encoding="utf-8", newline="") as fh:
                stray |= {r["person_id"] for r in csv.DictReader(fh)} - top
        check(f"  {level}: bundle person ids exist at the top level", not stray,
              f"{len(stray)} do not, e.g. {sorted(stray)[:3]}")

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


def check_layout() -> None:
    """Unit checks on the figure geometry, no data needed.

    Both guard bugs that made a figure lie rather than crash: an outlier that
    squashed every other node into a dot, and labels drawn off the canvas.
    """
    print("make_figures geometry", file=sys.stderr)
    from make_figures import _text_width, normalise, radius

    # A spring layout typically throws one node far out. Fitting to the true
    # extremes then collapses the rest; the robust fit must not.
    pos = {f"n{i}": (i / 100.0, i / 100.0) for i in range(40)}
    pos["far"] = (60.0, 60.0)
    naive = normalise(pos, 300, 300, pad=10)
    robust = normalise(pos, 300, 300, pad=10, robust=0.03)

    def spread(p):
        xs = [v[0] for k, v in p.items() if k != "far"]
        return max(xs) - min(xs)

    check("  naive fit collapses the body of the layout", spread(naive) < 10,
          f"spread {spread(naive):.1f}")
    check("  robust fit keeps the body spread out", spread(robust) > 200,
          f"spread {spread(robust):.1f}")
    # Clamping keeps the outlier on the canvas rather than off it.
    for name, p in (("naive", naive), ("robust", robust)):
        inside = all(0 <= x <= 300 and 0 <= y <= 300 for x, y in p.values())
        check(f"  {name} fit leaves every node on the canvas", inside)

    # Area-proportional sizing: four times the degree is twice the radius,
    # net of the floor. Never a linear radius, which over-reads big nodes.
    r_lo, r_mid, r_hi = radius(0, 0, 100), radius(25, 0, 100), radius(100, 0, 100)
    check("  radius is area-proportional",
          abs((r_mid - r_lo) * 2 - (r_hi - r_lo)) < 0.01,
          f"{r_lo:.2f} {r_mid:.2f} {r_hi:.2f}")
    check("  text width estimate grows with the string",
          _text_width("Banque de l'Indochine", 11) > _text_width("Banque", 11) > 0)


def _texts_with_size(node, ns, inherited=11.0):
    """Yield (text element, effective font size).

    `font-size` is set on the enclosing <g>, not on each <text>, so reading it
    off the element alone measures every label at the default 11px. That is
    what made the check flag 10.5px territory labels as overflowing: it was
    measuring a font nobody renders.
    """
    size = float(node.get("font-size", inherited))
    if node.tag == f"{ns}text":
        yield node, size
    for child in node:
        yield from _texts_with_size(child, ns, size)


def check_labels() -> None:
    """Every French category in the data must have an English label."""
    from labels import coverage, to_en

    print("English labels", file=sys.stderr)
    docs = load("documents.csv")
    for kind, col in (("territory", "country"), ("region", "region"),
                      ("sector", "sector")):
        gaps = coverage((d[col] for d in docs), kind)
        check(f"  every {kind} has an English label", not gaps, str(gaps[:4]))

    # A few spot translations, so a corrupted or truncated table is caught
    # rather than silently falling back to the French.
    for src, want in (("Maroc", "Morocco"), ("Indochine", "Indochina"),
                      ("Afrique occidentale française", "French West Africa"),
                      ("Algérie", "Algeria"), ("Tunisie", "Tunisia")):
        eq(f"  {src} -> {want}", to_en(src), want)

    # Firm names are legal names, not descriptions: translating them would
    # invent names that appear in no archive. The English figures must carry
    # them through unchanged.
    en_fig = os.path.join(ROOT, "figures", "en", "fig1_core_interlocks.svg")
    if os.path.exists(en_fig):
        with open(en_fig, encoding="utf-8") as fh:
            txt = fh.read()
        check("  English figures keep firm names in French",
              "Banque de l\u2019Indochine" in txt or "Banque de l'Indochine" in txt,
              "ego firm name missing from the English figure")
        # Assert on the English strings, not the absence of the French ones:
        # a firm in this corpus is literally labelled "Maroc", so "no Maroc
        # anywhere" fails on a correct figure.
        fr_fig = os.path.join(ROOT, "figures", "fig1_core_interlocks.svg")
        with open(fr_fig, encoding="utf-8") as fh:
            fr_txt = fh.read()
        # Derived from the figure, not hardcoded: which three territories are
        # largest depends on the data, and Maroc dropped out of the top three
        # when the annuaire genres were merged.
        from make_figures import CORE_H, CORE_W, prepare_core
        from build_network import read_csv as _read

        _, _, top3, _ = prepare_core({r["company_id"]: r for r in
                                      _read("companies.csv")}, 170, 2,
                                     CORE_W, CORE_H)
        for src in top3:
            want = to_en(src)
            check(f"  English legend carries {want!r} for {src!r}", want in txt)
            if want != src:
                check(f"  source figure keeps {src!r}, not {want!r}",
                      want not in fr_txt, f"{want} leaked into the French figure")


def check_org_key() -> None:
    """org_key must not be defeated by the name's own opening words."""
    print("names.org_key", file=sys.stderr)
    cases = [
        # The predecessor clause is a *tail*. A name that opens with it used to
        # be consumed whole: Peyrissac, a major AOF trading house, lost 72
        # observations this way.
        ("Anciens Établissements Ch. Peyrissac et Cie", "anciensetablissementschpeyrissac"),
        ("Anciens Établissements Eiffel", "anciensetablissementseiffel"),
        # Mid-word matches: "anc" inside "Blanc", "ex" inside "Alex".
        ("Grande Maison de Blanc", "grandemaisonblanc"),
        ("Alex. Bury. Cie minière", "alexburyminiere"),
        ("Société Altex", "altex"),
        # A real trailing predecessor clause is still stripped.
        ("Compagnie du Maroc (anciennement Société marocaine)", "maroc"),
        # All-stopword names get a slug rather than an empty key...
        ("Société générale", "societegenerale"),
        # ...but a bare legal form is not a firm and must stay unkeyed.
        ("Société", ""),
        ("Société anon.", ""),
        ("Compagnie", ""),
        # Unchanged behaviour on ordinary names.
        ("Banque de l'Indochine", "banqueindochine"),
    ]
    for raw, want in cases:
        eq(f"  org_key({raw[:34]!r})", org_key(raw), want)


def check_person_index() -> None:
    """The inverted-index parser: its two failure modes are silent."""
    from parse_person_index import (REF_RE, gloss_agrees, role_of,
                                    split_name, strip_brackets)

    print("person-index parser", file=sys.stderr)

    # Failure mode 1: numbers inside bracketed notes read as company
    # references. Life dates fall squarely in the company-number range, so a
    # fabricated tie looks entirely plausible.
    entry = "Abinal (Patrice)[1883-1961][ing.-conseil, anc. adm.], 1613 (Applications)."
    stripped = strip_brackets(entry)
    check("  bracketed life dates are stripped before refs are read",
          "1883" not in stripped and "1961" not in stripped and "1613" in stripped,
          repr(stripped))
    name, rest = split_name(stripped)
    refs = [n for n, _ in REF_RE.findall(rest or "")]
    eq("  only the real reference survives", refs, ["1613"])

    # Failure mode 2: an unmatched '[' pairs with a ']' far below and the
    # regex deletes most of the document - which looks like a clean parse of
    # a much smaller source rather than like an error.
    runaway = "A (x), 11 (one).\n" + "B [unclosed, 22 (two).\n" + "C (y), 33 (three).\n"
    out = strip_brackets(runaway)
    check("  an unmatched bracket does not eat the document",
          len(out) > 0.8 * len(runaway) and "33" in out,
          f"{len(out)} of {len(runaway)} chars survived")

    # The genre guarantees "Surname (Given)". The general parser guesses, and
    # on "Baert (J.)" it guesses backwards - forename "Baert", surname "J." -
    # so 148 distinct people collapsed onto the key `j-b` and generated
    # thousands of interlock edges between firms that never shared a director.
    from parse_person_index import parse_index_name
    for raw, surname, key in [
        ("Baert (J.)", "Baert", "baert-j"),
        ("Bailly (J.)", "Bailly", "bailly-j"),
        ("Achard (Georges-P.)", "Achard", "achard-g"),
        ("Abaza (Mohamed Aziz)", "Abaza", "abaza-m"),
        ("Abadie", "Abadie", "abadie"),
        # A trailing particle belongs in front of the surname.
        ("Abs (P. d\u2019)", "d'Abs", "d-abs-p"),
        ("Aboville (J. d\u2019)", "d'Aboville", "d-aboville-j"),
    ]:
        got = parse_index_name(raw)
        eq(f"  parse_index_name({raw!r}).surname", got["surname"], surname)
        eq(f"  parse_index_name({raw!r}).key", got["person_key"], key)
    keys = {parse_index_name(f"{s} (J.)")["person_key"]
            for s in ("Baert", "Bagage", "Bailly", "Balaresque")}
    eq("  four different B-surnames give four different keys", len(keys), 4)

    # Role abbreviations peculiar to the annuaire.
    for gloss, want in (("comm. cptes Pyrites de Huelva", "commissaire_aux_comptes"),
                        ("pdt Nestlé Alimentana", "president"),
                        ("v.-pdt Crédit sarrois", "vice_president"),
                        ("dga BAO", "directeur_general"),
                        ("censeur Bq Algérie", "censeur"),
                        ("Land bank of Egypt", "administrateur")):
        eq(f"  role_of({gloss[:22]!r})", role_of(gloss), want)

    check("  gloss agreement detects a mismatch",
          gloss_agrees("Bq comm. afr.", "Banque commerciale africaine") is True
          and gloss_agrees("Nestlé", "Chemins de fer du Maroc") is False)

    path = os.path.join(PROC_DIR, "affiliations_person_index.csv")
    if not os.path.exists(path):
        return
    rows = load("affiliations_person_index.csv")
    check("  produced a substantial number of ties", len(rows) > 5000, str(len(rows)))
    nokey = [r for r in rows if not r["company_key"]]
    check("  every row resolves to a company", not nokey, str(len(nokey)))
    nolink = [r for r in rows if not r["person_key"] and not r["member_key"]]
    check("  every row has a person or a corporate member", not nolink,
          str(len(nolink)))
    brackets = [r for r in rows if "[" in r["company_name"]]
    check("  editorial notes are stripped from company names", not brackets,
          str([r["company_name"][:40] for r in brackets[:2]]))

    report = load("person_index_report.csv")
    for r in report:
        rate = float(r["gloss_agreement"])
        check(f"  {r['title'][:34]}: gloss agreement >= 0.90", rate >= 0.90,
              f"{rate:.3f} - the numbering may be misaligned")
        check(f"  {r['title'][:34]}: key is substantial",
              int(r["n_key_companies"]) > 500, r["n_key_companies"])


def check_prose_parser() -> None:
    """Stage 3c. Each case is an error the hand audit actually found."""
    from parse_prose import extract, names_from

    print("prose parser", file=sys.stderr)

    def people(text, company="Société des Mines de Zellidja"):
        out = []
        for names, role, trigger, _ in extract(text, company, []):
            out += [(n, role) for n in names]
        return out

    # Works at all.
    got = people("MM. Georges Thomas et Dal Piaz ont été réélus administrateurs.")
    eq("  reads an appointment in prose", sorted(n for n, _ in got),
       ["Dal Piaz", "Georges Thomas"])

    # A *singular* role after a run names only the last person. Reading it as
    # the whole run made eleven presidents of one company.
    got = people("MM. Meunier, Guibal, Godard, Billiard, président.")
    eq("  a singular role after a list binds the last name only",
       [n for n, _ in got], ["Billiard"])
    got = people("MM. Lutscher et Vigouroux, administrateurs.")
    eq("  a plural role binds the whole list", len(got), 2)

    # A non-compete clause uses the role words in the negative.
    eq("  a non-compete clause appoints nobody",
       people("M. Borgeaud s'interdit de diriger comme gérant, directeur."), [])

    # Decorations and addresses sit exactly where a name sits.
    check("  a decoration is not a person",
          "commandeur de la Légion d'honneur" not in names_from(
              "M. Antoine Nunzi, commandeur de la Légion d'honneur"))
    check("  a street address is not a person",
          not any("rue" in n.lower() for n in names_from(
              "M. Joseph de Traversay, demeurant à Paris, 10, rue de Laborde")))

    # Presiding a meeting is not holding a board seat.
    eq("  a mayor chairing a meeting is not the board president",
       people("sous la présidence de M. Louis Martin, maire"), [])
    check("  a chairman of the board is kept",
          any(r == "president" for _, r in people(
              "sous la présidence de M. Guynet, président du conseil "
              "d'administration")))

    # An occupation between the name and the role means the role is not held
    # at this firm.
    eq("  an occupation between name and role rejects the match",
       people("M. Willot, inspecteur général des Postes, président"), [])

    path = os.path.join(PROC_DIR, "affiliations_prose.csv")
    if not os.path.exists(path):
        return
    rows = load("affiliations_prose.csv")
    check("  prose file is substantial", len(rows) > 5000, str(len(rows)))
    bad = [r for r in rows if not r["company_key"] or not r["person_key"]]
    check("  every prose row is fully attributed", not bad, str(len(bad)))
    eq("  every prose row is tagged",
       {r["source_genre"] for r in rows}, {"prose"})


def check_annotation_resolver() -> None:
    """Stage 3d: abbreviation matching, and the guards it needed."""
    from resolve_annotations import (JUNK_NAME_RE, build_index, content,
                                     matches, resolve, tokens)

    print("annotation resolver", file=sys.stderr)

    # Prefix matching in order, which is what lets an abbreviation resolve.
    check("  'cotonn st quentin' prefixes 'cotonniere de saint quentin'",
          matches(content(tokens("Cotonn. St-Quentin")),
                  content(tokens("Cotonnière de Saint-Quentin"))))
    check("  'cie gen transatl' prefixes the full name",
          matches(content(tokens("Cie gén. transatl")),
                  content(tokens("Compagnie générale transatlantique"))))
    check("  out-of-order tokens do not match",
          not matches(content(tokens("quentin cotonn")),
                      content(tokens("Cotonnière de Saint-Quentin"))))

    # The junk filter must not be case-insensitive: under re.I a "^[a-z]"
    # class matches an uppercase initial, and the first version of this
    # pattern rejected every company name in the file.
    for good in ("Banque de l'Indochine", "Compagnie Générale des colonies",
                 "L'Air liquide", "Société des Messageries maritimes",
                 "Omnium lyonnais"):
        check(f"  JUNK_NAME_RE keeps {good[:28]!r}", not JUNK_NAME_RE.search(good))
    for junk in ("G., 1921-22 min. Int., 1928-30 min. Instruc.",
                 "Xavier Loisy: polytechnicien"):
        check(f"  JUNK_NAME_RE rejects {junk[:28]!r}", bool(JUNK_NAME_RE.search(junk)))

    index = build_index([
        {"company_id": "banqueindochine", "name": "Banque de l'Indochine"},
        {"company_id": "mineszellidja", "name": "Société des Mines de Zellidja"},
        {"company_id": "minesbouthaleb", "name": "Société des Mines du Bou-Thaleb"},
    ])
    from collections import defaultdict as _dd
    by_first = _dd(list)
    for i, (_, _, tk) in enumerate(index):
        for t in set(content(tk) or tk):
            by_first[t[:2]].append(i)

    cid, _, method = resolve("Bq de l'Indochine", index, by_first)
    eq("  'Bq de l'Indochine' resolves", cid, "banqueindochine")
    # "Mines" alone prefixes both mining firms: guessing would manufacture a
    # specific, checkable, wrong claim.
    cid, _, method = resolve("Mines", index, by_first)
    eq("  a note matching several firms is dropped", cid, "")
    check("  ...and says why",
          method in {"single_token", "generic_single_token", "ambiguous_2"}, method)

    path = os.path.join(PROC_DIR, "affiliations_annotations.csv")
    if not os.path.exists(path):
        return
    rows = load("affiliations_annotations.csv")
    check("  resolver produced ties", len(rows) > 500, str(len(rows)))
    self_ref = [r for r in rows if r["company_key"] == r["from_company_id"]]
    check("  no tie points back at the firm it was read from", not self_ref,
          str(len(self_ref)))
    eq("  every row is tagged", {r["source_genre"] for r in rows}, {"annotation"})


def check_biographies() -> None:
    """Stage 3e: person-scoped entries in biographical dictionaries."""
    from parse_biographies import affiliations_in, entries, split_list

    print("biographical parser", file=sys.stderr)

    doc = ("ACCAMBRAY (Léon), député\n"
           "[Administrateur : Compagnie céramique française (nommé mai 1921), "
           "Compagnie africaine de commerce]\n"
           "UNE ROSETTE BIEN PLACÉE (L'affaire)\n"
           "[administrateur de la Société fiduciaire de contrôle]\n"
           "ASPE-FLEURIMONT (Lucien)\n"
           "[administrateur de la Société fiduciaire de contrôle]\n")
    got = [name for name, _ in entries(doc)]
    check("  reads a capitalised entry header", any("ACCAMBRAY" in g for g in got))
    # A headline in capitals has the same shape as an entry header.
    check("  a capitalised headline is not a person",
          not any("ROSETTE" in g for g in got), str(got))

    # The parenthetical qualifier is not part of the company name.
    eq("  a company list splits on top-level commas only",
       split_list("Compagnie céramique française (nommé mai 1921), Banque X"),
       ["Compagnie céramique française", "Banque X"])

    roles = dict((n, r) for r, n in affiliations_in(
        "[Administrateur : Compagnie céramique française]"))
    eq("  a labelled list yields the role",
       roles.get("Compagnie céramique française"), "administrateur")
    roles = dict((n, r) for r, n in affiliations_in(
        "président de la Société fiduciaire de contrôle"))
    check("  a governed noun phrase yields the role",
          any(r == "president" for r in roles.values()), str(roles))

    path = os.path.join(PROC_DIR, "affiliations_biographical.csv")
    if not os.path.exists(path):
        return
    rows = load("affiliations_biographical.csv")
    check("  produced ties", len(rows) > 1000, str(len(rows)))
    bad = [r for r in rows if not r["company_key"] or not r["person_key"]]
    check("  every row is fully attributed", not bad, str(len(bad)))
    eq("  every row is tagged", {r["source_genre"] for r in rows}, {"biographical"})
    # These entries give a career, not a board list for a year.
    eq("  biographical ties carry no year", {r["year"] for r in rows}, {""})


def check_geocoding() -> None:
    """The city gazetteer and the address parser."""
    from geocode import fold, head_office_prefix, load_gazetteer, match_city

    print("geocoding", file=sys.stderr)
    index, cities = load_gazetteer()
    check("  gazetteer loads", len(cities) > 100, f"{len(cities)} cities")

    bad = [c for c, r in cities.items()
           if not (-90 <= float(r["lat"]) <= 90 and -180 <= float(r["lon"]) <= 180)]
    check("  every city has plausible coordinates", not bad, str(bad[:3]))
    at_null = [c for c, r in cities.items()
               if abs(float(r["lat"])) < 0.01 and abs(float(r["lon"])) < 0.01]
    check("  no city sits at Null Island", not at_null, str(at_null[:3]))

    # The failure this parser exists to prevent: Paris street names include
    # rue de Rome, rue de Constantinople and rue d'Alger, so searching a whole
    # head-office string for city names puts Paris firms in Italy.
    for raw, want in [
        ("Paris, 1, rue de Stockholm. Tél. : LAB. 18-34", "Paris"),
        ("Paris, 12, rue de Rome", "Paris"),
        ("Paris, 5, rue d'Alger", "Paris"),
        ("Paris, 40, rue de Constantinople", "Paris"),
        ("le siège social est à Saïgon", "Saïgon"),
        ("CASABLANCA (Maroc)", "Casablanca"),
        ("Alger, 3, boulevard Baudin", "Alger"),
    ]:
        eq(f"  {raw[:34]!r} -> {want}",
           match_city(head_office_prefix(raw), index), want)

    eq("  fold() is accent-insensitive", fold("Saïgon"), fold("Saigon"))
    eq("  fold() is case-insensitive", fold("DAKAR"), fold("Dakar"))

    path = os.path.join(PROC_DIR, "company_places.csv")
    if not os.path.exists(path):
        return
    rows = load("company_places.csv")
    placed = [r for r in rows if r["city"]]
    unknown = sorted({r["city"] for r in placed} - set(cities))
    check("  every placed city is in the gazetteer", not unknown, str(unknown[:3]))
    nocoord = [r["company_id"] for r in placed if not r["lat"] or not r["lon"]]
    check("  every placed firm has coordinates", not nocoord, str(nocoord[:3]))
    check("  coverage is reported, not silently total",
          0 < len(placed) < len(rows),
          f"{len(placed)} of {len(rows)} - a total is suspicious")

    edges_path = os.path.join(PROC_DIR, "edges_city_interlock.csv")
    if os.path.exists(edges_path):
        edges = load("edges_city_interlock.csv")
        # Parenthesised: `a | b - c` binds as `a | (b - c)`, which would only
        # ever check the second column.
        seen = ({e["city_1"] for e in edges} | {e["city_2"] for e in edges})
        stray = sorted(seen - set(cities))
        check("  city edges reference known cities", not stray, str(stray[:3]))
        self_loops = [e for e in edges if e["city_1"] == e["city_2"]]
        check("  city edges are between distinct cities", not self_loops,
              f"{len(self_loops)} self-loops - within-city ties belong in the table")


_ROTATE_RE = re.compile(r"rotate\(\s*(-?[\d.]+)")
_TRANSLATE_RE = re.compile(r"translate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)")


def _translate_of(transform: str) -> tuple[float, float]:
    m = _TRANSLATE_RE.search(transform or "")
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def check_structure_figures() -> None:
    """The structural figures state facts about the graph. Assert the facts.

    These are the numbers a reader is most likely to quote back — "the network
    is one component", "half of it survives a weight filter", "the deepest core
    is a clique" — and each of them is a sentence in a caption. A caption that
    drifts from the data is worse than no caption, so every claim that a figure
    makes in words is pinned here against the graph it was computed from.
    """
    import make_network_figures as N

    print("structural figures", file=sys.stderr)
    d = N.gather("fr")
    G = d["G"]

    # fig21's whole point: one shared director holds the graph together, two
    # do not. If that gap ever closed the caption would be saying the opposite
    # of the data.
    one, two = d["thresholds"][0]["share"], d["thresholds"][1]["share"]
    check("  fig21: the graph is one component at weight >= 1", one > 0.9,
          f"{one:.1%}")
    check("  fig21: less than two thirds of it survives weight >= 2", two < 0.66,
          f"{two:.1%}")

    # fig19 and fig26 both call the deepest core a complete graph. That is a
    # measurable claim, not a turn of phrase.
    kmax = max(d["core"].values())
    inner = [n for n, k in d["core"].items() if k == kmax]
    eq("  fig19: the deepest shell has k+1 members", len(inner), kmax + 1)
    check("  fig19/26: the deepest shell is a complete graph",
          d["shell_density"][kmax] > 0.999, f"{d['shell_density'][kmax]:.4f}")
    # ... and that it is one person's doing, which is what fig26 draws.
    S = set(inner)
    holds = sum(1 for u, v, a in G.edges(data=True)
                if u in S and v in S and N.HOLDER in a["directors"])
    eq(f"  fig26: {N.HOLDER} sits on every firm in it",
       holds, len(inner) * (len(inner) - 1) // 2)

    # fig22 samples; a sample that moved with the process would move the
    # figure. The seeded RNG draws from a sorted list precisely so it cannot.
    rng_a = random.Random(N.PATH_SEED).sample(d["giant"], 8)
    rng_b = random.Random(N.PATH_SEED).sample(sorted(d["giant"]), 8)
    check("  fig22: the path sample is drawn from a sorted list",
          rng_a == rng_b, "the giant component is not in sorted order")

    # fig23's finding is that no community is territorially pure. State it as
    # a bound rather than as an adjective.
    worst = 0.0
    for counts in d["comm_terr"][:12]:
        total = sum(counts.values()) or 1
        worst = max(worst, max(counts.values()) / total)
    check("  fig23: no large community is territorially pure", worst < 0.9,
          f"most homogeneous is {worst:.0%}")

    # fig24 quotes a share over the whole graph; the per-period rows have to
    # add up to the same population.
    w, a, _u = d["cross_all"]
    eq("  fig24: every interlock edge is classified",
       w + a + _u, G.number_of_edges())

    # Every structural figure ships its table, for the same reason the
    # descriptive ones do.
    for lang in ("fr", "en"):
        dl = d if lang == "fr" else N.gather(lang)
        for name, fn, _ in N.FIGURES:
            *_, table = fn(dl, "light", lang)
            check(f"  {name} ({lang}) ships a table view",
                  bool(table and table[0] and table[1]))

    # The measures file is what makes the captions quotable. It must exist and
    # agree with the graph it claims to describe.
    rows = {r["measure"]: r["value"] for r in load("network_measures.csv")}
    if rows:
        eq("  network_measures.csv agrees on the firm count",
           rows.get("n_firms"), str(G.number_of_nodes()))
        eq("  network_measures.csv agrees on the edge count",
           rows.get("n_interlocks"), str(G.number_of_edges()))
        eq("  network_measures.csv agrees on the deepest core",
           rows.get("max_core_number"), str(kmax))
    else:
        check("  network_measures.csv exists", False)


def check_figures() -> None:
    """The rendered figures must be well-formed, on-canvas and comparable."""
    import xml.etree.ElementTree as ET

    fig_dir = os.path.join(ROOT, "figures")
    if not os.path.isdir(fig_dir):
        return
    print("figures", file=sys.stderr)
    from make_figures import PALETTE, _text_width

    import glob as _glob

    # Every figure gets the same geometry guards, in every language tree.
    # They are generated in a loop, so a bug in one is a bug in ninety-four.
    svgs = sorted(os.path.relpath(f, fig_dir) for f in
                  _glob.glob(os.path.join(fig_dir, "**", "*.svg"), recursive=True))
    for name in svgs:
        path = os.path.join(fig_dir, name)
        if not os.path.exists(path):
            check(f"  {name} exists", False)
            continue
        try:
            root = ET.parse(path).getroot()
        except Exception as exc:  # noqa: BLE001
            check(f"  {name} is well-formed XML", False, str(exc))
            continue
        check(f"  {name} is well-formed XML", True)
        w, h = (float(v) for v in root.get("viewBox").split()[2:])
        ns = "{http://www.w3.org/2000/svg}"

        # Nodes on the canvas. A node drawn outside the viewBox is invisible
        # and silently drops a firm from the figure.
        off = [
            (c.get("cx"), c.get("cy"))
            for c in root.iter(f"{ns}circle")
            if not (0 <= float(c.get("cx")) <= w and 0 <= float(c.get("cy")) <= h)
        ]
        check(f"  {name}: every node is inside the canvas", not off, str(off[:3]))

        # Labels on the canvas, measured the way the renderer measures them.
        # Margin labels used to run off the right edge and get clipped.
        clipped = []
        for t, size in _texts_with_size(root, ns):
            tw = _text_width("".join(t.itertext()), size)
            transform = t.get("transform") or (t.getparent().get("transform")
                                               if hasattr(t, "getparent") else None)
            if transform:
                # A rotated label runs along its own axis, so its footprint on
                # each canvas axis is the projection of its width. Handling only
                # the -90 case treated the arc diagram's 60-degree firm names as
                # vertical and measured them against the wrong edge entirely.
                m = _ROTATE_RE.search(transform)
                deg = float(m.group(1)) if m else -90.0
                rad = math.radians(deg)
                ox, oy = _translate_of(transform)
                x = float(t.get("x", 0)) + ox
                y = float(t.get("y", 0)) + oy
                # text-anchor start: the run goes forward along the rotated axis.
                sign = -1.0 if t.get("text-anchor") == "end" else 1.0
                x1 = x + sign * tw * math.cos(rad)
                y1 = y + sign * tw * math.sin(rad)
                lo_x, hi_x = min(x, x1), max(x, x1)
                lo_y, hi_y = min(y, y1), max(y, y1)
                if lo_x < -0.5 or hi_x > w + 0.5 or lo_y < -0.5 or hi_y > h + 0.5:
                    clipped.append(("".join(t.itertext())[:24], f"rot{deg:g}",
                                    (round(lo_x), round(hi_x),
                                     round(lo_y), round(hi_y))))
                continue
            x = float(t.get("x", 0))
            # SVG places the anchor point, not the left edge. Handling only
            # "end" made every *centred* label near the right edge look clipped
            # by half its width, which is a false positive rather than a bug in
            # the figure.
            anchor = t.get("text-anchor")
            if anchor == "end":
                x0 = x - tw
            elif anchor == "middle":
                x0 = x - tw / 2
            else:
                x0 = x
            if x0 < -0.5 or x0 + tw > w + 0.5:
                clipped.append(("".join(t.itertext())[:24], round(x0), round(x0 + tw)))
        check(f"  {name}: no label is clipped by the canvas", not clipped,
              str(clipped[:3]))

        # The all-pairs cap: at most three categorical hues, plus grey. The
        # sequential ramp is allowed only on rects (the matrix cells) - a node
        # coloured from a magnitude ramp would be encoding twice.
        #
        # Slots 4 and 5 are allowed as well, for the descriptive figures' stacked
        # bars. A stack is an *adjacent*-pair form, and the five-slot set passes
        # every hard gate on the adjacent pairlist in both modes (worst CVD
        # ΔE 9.1 light / 8.4 dark, worst normal-vision ΔE 19.6 / 19.3). The
        # three-slot cap still binds on the all-pairs forms - node-link diagrams
        # and the map - which is why the two extra hues appear on no circle.
        from make_descriptive_figures import EXTRA_SERIES
        from make_territory_figures import SEQ

        allowed = set(PALETTE["light"]["series"]) | {
            PALETTE["light"]["other"], PALETTE["light"]["surface"],
            PALETTE["light"]["edge"], "none",
        }
        stack_allowed = allowed | set(EXTRA_SERIES["light"])
        extra = {c.get("fill") for c in root.iter(f"{ns}circle")} - stack_allowed
        check(f"  {name}: no colour outside the validated palette", not extra,
              str(sorted(extra)[:3]))
        # Strokes are an encoding too. `draw.curved_edges` gives an edge a
        # colour when it carries a category, and nothing was checking that the
        # colour came from the palette — the arc diagram's two edge hues and the
        # backbone's grey step are as much a categorical encoding as any node
        # fill, and the first version of the backbone painted its cross-territory
        # edges in the same orange as its Algeria nodes.
        stroke_allowed = stack_allowed | {
            PALETTE["light"]["hairline"], PALETTE["light"]["text_muted"],
            PALETTE["light"]["text_primary"], PALETTE["light"]["text_secondary"],
        }
        extra_s = set()
        for tag in ("path", "line", "circle", "rect", "text"):
            extra_s |= {e.get("stroke") for e in root.iter(f"{ns}{tag}")}
        extra_s = {c for c in extra_s if c} - stroke_allowed
        check(f"  {name}: no stroke colour outside the palette", not extra_s,
              str(sorted(extra_s)[:3]))

        extra_r = ({r.get("fill") for r in root.iter(f"{ns}rect")}
                   - stack_allowed - set(SEQ["light"]))
        check(f"  {name}: no rect colour outside the palette", not extra_r,
              str(sorted(x for x in extra_r if x)[:3]))

    # Small multiples must share one coordinate frame, or a reader comparing
    # panels is comparing two different maps.
    path = os.path.join(fig_dir, "fig2_by_period.svg")
    if os.path.exists(path):
        root = ET.parse(path).getroot()
        ns = "{http://www.w3.org/2000/svg}"
        seen: dict[str, set] = {}
        for g in root.iter(f"{ns}g"):
            for c in g.iter(f"{ns}circle"):
                cid = c.get("data-id")
                if cid:
                    seen.setdefault(cid, set()).add((c.get("cx"), c.get("cy")))
        moved = {k: v for k, v in seen.items() if len(v) > 1}
        check("  fig2: a firm sits at the same point in every panel", not moved,
              str(list(moved)[:3]))
        check("  fig2: panels share firms to compare",
              any(len(v) >= 1 for v in seen.values()) and len(seen) > 20,
              f"{len(seen)} firms")

    # Figure 4 is captioned "every firm". Assert that literally: the drawn
    # node count must equal the interlock graph's, or the caption is a lie.
    path = os.path.join(fig_dir, "fig4_empire_network.svg")
    if os.path.exists(path):
        from make_figures import build_interlock_graph

        G = build_interlock_graph(1)
        root = ET.parse(path).getroot()
        ns = "{http://www.w3.org/2000/svg}"
        drawn = {c.get("data-id") for c in root.iter(f"{ns}circle") if c.get("data-id")}
        eq("  fig4 draws every firm in the interlock graph",
           len(drawn), G.number_of_nodes())
        check("  fig4 draws the firms the graph has, not others",
              drawn == set(G.nodes()), str(sorted(drawn ^ set(G.nodes()))[:3]))

    # Same guarantee per territory, against that territory's own bundle.
    from make_territory_figures import read_bundle_edges

    bad, checked = [], 0
    for f in _glob.glob(os.path.join(fig_dir, "by_country", "*.svg")):
        slug = os.path.basename(f)[:-4]
        rows = read_bundle_edges("country", slug)
        want = {r["company_id_1"] for r in rows} | {r["company_id_2"] for r in rows}
        root = ET.parse(f).getroot()
        ns = "{http://www.w3.org/2000/svg}"
        got = {c.get("data-id") for c in root.iter(f"{ns}circle") if c.get("data-id")}
        checked += 1
        if got != want:
            bad.append(f"{slug}: drew {len(got)} of {len(want)}")
    check(f"  every territory figure draws its whole bundle ({checked} figures)",
          not bad, "; ".join(bad[:3]))

    # A territory with interlocks must have a figure; one without must not.
    with open(os.path.join(ROOT, "data", "by_country", "territory_manifest.csv"),
              encoding="utf-8", newline="") as fh:
        manifest = list(csv.DictReader(fh))
    have = {os.path.basename(f)[:-4]
            for f in _glob.glob(os.path.join(fig_dir, "by_country", "*.svg"))}
    missing = [r["slug"] for r in manifest
               if int(r["n_interlock_edges"]) > 0 and r["slug"] not in have]
    check("  every territory with an interlock has a figure", not missing,
          str(missing[:4]))
    spurious = [r["slug"] for r in manifest
                if int(r["n_interlock_edges"]) == 0 and r["slug"] in have]
    check("  no figure for a territory with no interlock", not spurious,
          str(spurious[:4]))

    # The matrix is an undirected relation, so both triangles must be drawn:
    # a half-filled matrix reads as an asymmetric one.
    path = os.path.join(fig_dir, "fig5_territory_matrix.svg")
    if os.path.exists(path):
        root = ET.parse(path).getroot()
        ns = "{http://www.w3.org/2000/svg}"
        pairs = Counter()
        for r in root.iter(f"{ns}rect"):
            if r.get("data-a"):
                pairs[(r.get("data-a"), r.get("data-b"), r.get("data-v"))] += 1
        check("  fig5 draws both triangles for every pair",
              pairs and all(v == 2 for v in pairs.values()),
              str([k for k, v in pairs.items() if v != 2][:2]))

    # The English tree must mirror the source tree file for file: a partial
    # translation is worse than none, because the gap is invisible.
    en_dir = os.path.join(fig_dir, "en")
    if os.path.isdir(en_dir):
        fr = {os.path.relpath(f, fig_dir) for f in
              _glob.glob(os.path.join(fig_dir, "**", "*.svg"), recursive=True)
              if os.sep + "en" + os.sep not in f}
        en = {os.path.relpath(f, en_dir) for f in
              _glob.glob(os.path.join(en_dir, "**", "*.svg"), recursive=True)}
        eq("  the English tree mirrors the source tree", len(en), len(fr))
        check("  no figure is missing from the English tree", en == fr,
              str(sorted(fr - en)[:3]))

    for page_name in ("interlock_network.html", "territory_networks.html",
                      os.path.join("en", "interlock_network.html"),
                      os.path.join("en", "territory_networks.html")):
        page = os.path.join(fig_dir, page_name)
        if not os.path.exists(page):
            continue
        with open(page, encoding="utf-8") as fh:
            txt = fh.read()
        for token in ('<table', 'class="legend"', 'class="tooltip"',
                      "prefers-color-scheme"):
            check(f"  {page_name} carries {token}", token in txt)
        check(f"  {page_name} is self-contained (no external fetch)",
              "http://" not in txt.replace("http://www.w3.org", ""),
              "external URL in page")

    # Identity must never rest on colour alone: the legend, the table view and
    # the dark-mode pair above are what the palette's contrast WARN obliges.

    # Every figure must exist as a raster too, and the raster must be current.
    # A stale PNG beside a rebuilt SVG is the failure mode worth catching:
    # it looks like a figure and shows the previous run's data.
    missing, stale, tiny = [], [], []
    for svg in svgs:
        svg_path = os.path.join(fig_dir, svg)
        png_path = svg_path[:-4] + ".png"
        if not os.path.exists(svg_path):
            continue
        if not os.path.exists(png_path):
            missing.append(svg)
        elif os.path.getmtime(png_path) < os.path.getmtime(svg_path) - 1:
            stale.append(svg)
        elif os.path.getsize(png_path) < 3000:
            tiny.append(svg)
    check(f"  every figure has a PNG ({len(svgs)} figures)", not missing,
          str(missing[:4]))
    check("  no PNG is older than its SVG", not stale, str(stale[:4]))

    # The figures must not depend on Python's per-process string hashing.
    # `spring_layout` assigns seeded coordinates in node-iteration order, and a
    # NetworkX subgraph view iterates a set of node names, so for a long time
    # re-running the pipeline on unchanged data rewrote 18 of the 98 figures
    # while every seed in the module was fixed. Building the same core graph
    # under two hash seeds is the cheap end of that test: the node order it
    # hands to the layout must match.
    import subprocess

    probe = (
        "import sys; sys.path.insert(0, %r);"
        "import make_figures as M;"
        "G = M.build_interlock_graph(2);"
        "print(' '.join(list(M.core_subgraph(G, 40))))" % os.path.join(ROOT, "src")
    )
    # Stage 12 adds three more set-shaped sources of the same bug:
    # `connected_components`, `core_number` and `louvain_communities` all hand
    # back sets or dicts keyed by node name. The partition in particular is a
    # figure's entire content, so it gets the same two-seed probe.
    comm_probe = (
        "import sys; sys.path.insert(0, %r);"
        "import make_network_figures as N;"
        "G = N.load_graph();"
        "print(len(N.sorted_components(G)),"
        " '|'.join(c[0] for c in N.louvain(G)[:12]))" % os.path.join(ROOT, "src")
    )
    # Stage 13's arc diagram takes a subgraph of the interlock graph, and a
    # NetworkX subgraph *view* iterates a set: the arcs landed in the same
    # places under two hash seeds and the path segments came out in a different
    # order, so the committed SVG changed on a re-run of unchanged data.
    arc_probe = (
        "import sys; sys.path.insert(0, %r);"
        "import make_node_figures as N;"
        "G = N.gather()['G'];"
        "K = N.ordered_subgraph(G, sorted(list(G)[:400]));"
        "print(' '.join(f'{u}~{v}' for u, v in list(K.edges())[:40]))"
        % os.path.join(ROOT, "src")
    )
    orders = []
    communities = []
    arc_edges = []
    for hashseed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=hashseed)
        for cmd, sink in ((probe, orders), (comm_probe, communities),
                          (arc_probe, arc_edges)):
            out = subprocess.run([sys.executable, "-c", cmd], capture_output=True,
                                 text=True, env=env, cwd=ROOT)
            sink.append(out.stdout.strip())
    # Every written table must carry a *total* sort order. A sort whose key
    # leaves ties is resolved by whatever order the rows arrived in, and that
    # order comes from dicts and sets keyed by name — so the row order churned
    # between runs on unchanged data. Re-sorting a committed file by its own
    # documented key has to reproduce the file.
    totally_sorted = [
        ("edges_company_interlock.csv",
         lambda r: (-int(r["weight"]), r["company_id_1"], r["company_id_2"])),
        ("edges_company_interlock_by_period.csv",
         lambda r: (r["period"], -int(r["weight"]),
                    r["company_id_1"], r["company_id_2"])),
        ("company_duplicate_candidates.csv",
         lambda r: (r["reason"], r["company_id_1"], r["company_id_2"])),
        ("edges_person_comembership.csv",
         lambda r: (-int(r["weight"]), r["person_id_1"], r["person_id_2"])),
    ]
    for name, key in totally_sorted:
        rows = load(name)
        if not rows:
            continue
        check(f"  {name} is in a total sort order", rows == sorted(rows, key=key),
              "row order is not reproducible from its own key")

    # The descriptive figures exist to make the caveats visible, so the numbers
    # they state have to be the committed ones. These pin the two that a reader
    # is most likely to quote back.
    import make_descriptive_figures as D

    for lang in ("fr", "en"):
        d = D.gather(lang)
        peak_year, peak = max(d["by_year"].items(), key=lambda kv: sum(kv[1].values()))
        eq(f"  fig8 ({lang}): the spike year is the annuaire's", peak_year, "1956")
        dated = sum(sum(c.values()) for c in d["by_year"].values())
        check(f"  fig8 ({lang}): the spike is a fifth of all dated observations",
              0.15 <= sum(peak.values()) / dated <= 0.25,
              f"{sum(peak.values()) / dated:.1%}")
        # The person index is what makes periods incomparable; if it ever leaks
        # outside 1945-62 the caption in fig9 stops being true.
        leaked = [p for p, c in d["by_period"].items()
                  if c.get("person_index") and p != "1945_1962"]
        check(f"  fig9 ({lang}): the person index stays inside 1945-62", not leaked,
              str(leaked))
        # Every figure must produce a table: the light-mode contrast warning on
        # three slots makes the table view an obligation, not a nicety.
        for name, fn, _ in D.FIGURES:
            *_, table = fn(d, "light", lang)
            check(f"  {name} ({lang}) ships a table view",
                  bool(table and table[0] and table[1]))

    check_structure_figures()

    check("  core graph node order is independent of PYTHONHASHSEED",
          orders[0] and orders[0] == orders[1],
          f"{orders[0][:60]!r} vs {orders[1][:60]!r}")
    check("  components and communities are independent of PYTHONHASHSEED",
          communities[0] and communities[0] == communities[1],
          f"{communities[0][:60]!r} vs {communities[1][:60]!r}")
    check("  node-level subgraph edge order is independent of PYTHONHASHSEED",
          arc_edges[0] and arc_edges[0] == arc_edges[1],
          f"{arc_edges[0][:60]!r} vs {arc_edges[1][:60]!r}")
    check("  no PNG is suspiciously small", not tiny, str(tiny[:4]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", action="store_true", help="parser checks only")
    args = ap.parse_args()

    check_names()
    check_urls()
    check_titles()
    check_citations()
    check_layout()
    check_labels()
    check_org_key()
    if not args.unit:
        check_extraction()
        check_dataset()
        check_positionality()
        check_splits()
        check_person_index()
        check_prose_parser()
        check_annotation_resolver()
        check_biographies()
        check_geocoding()
        check_figures()

    total = CHECKS["passed"] + CHECKS["failed"]
    print(f"\n{CHECKS['passed']}/{total} checks passed", file=sys.stderr)
    if FAILURES:
        print("\nfailures:", file=sys.stderr)
        for f in FAILURES:
            print(f"  - {f}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
