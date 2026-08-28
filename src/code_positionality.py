"""Stage 6 - code each person by their position in the colonial order.

Produces `person_positionality.csv`: for every person node, a coding of
whether they belonged to the colonising population or to a colonised one,
with the evidence and a confidence level.

    positionality        colonial | native | intermediate |
                         local_non_french_elite | unclassified
    positionality_group  the finer origin group the evidence points to
    confidence           high | medium | low
    evidence             which rules fired, semicolon-joined

**The only evidence is the name as printed, plus the territory the person's
ties were observed in.** This is onomastic inference. It is standard practice
in colonial business history for exactly this kind of source, and it is also
the weakest variable in this dataset. It supports statements about
*aggregate composition* ("indigenous names are 0.7% of board members in
Morocco"); it does not establish the origin of any named individual, and
should never be presented as though it did.

Why the categories are not a clean binary
-----------------------------------------
The request is for `colonial` / `native`, and those are the two main values.
Two groups are deliberately not forced into them:

- `intermediate` — Maghrebi Jewish names. Algerian Jews became French
  citizens by the Cremieux decree of 1870 while Muslim Algerians remained
  French *subjects*; Moroccan and Tunisian Jews did neither. Their position
  is between the two by construction, and a large literature turns on it.
- `local_non_french_elite` — Ottoman, Egyptian, Turkish, Armenian and Greek
  names in the Near East pages. Egypt and the Ottoman Empire were not French
  colonies, so an Egyptian pasha on a French-owned company's board is not a
  colonial subject of France. Syria-Lebanon, being a French mandate, is the
  exception and is coded `native`.

Collapse either into the binary yourself if your design calls for it; the
group is retained so the choice is yours and is visible.

The rules, and the rules that were rejected, are documented in
`data/reference/positionality_rules.md`. Read it before trusting a number.

Usage
    python3 src/code_positionality.py
    python3 src/code_positionality.py --candidates   # print coded non-Europeans
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_network import BOARD_ROLES, period_of, read_csv, write_csv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC_DIR = os.path.join(ROOT, "data", "processed")


def na(text: str) -> str:
    """Accent-stripped lower case, for matching."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    ).lower()


# --- name quality --------------------------------------------------------
# Particles and honorifics legitimately start a name in lower case, so a bare
# "starts lower case" test would reject "de Solages" and "prince d'Essling".
NAME_LOWER_OK = re.compile(
    r"^(?:de|du|des|d'|van|von|le|la|les|di|da|el|ben|bou|ould|"
    r"prince|comte|baron|vicomte|marquis|duc|chev|off|dr|me|mgr)\b",
    re.I,
)
# A sentence boundary needs a lower-case word of 2+ characters before the
# stop, so "O. Homberg" (an initial) survives but "cotonnades. Mohamed" does not.
NAME_ARTEFACT = re.compile(
    r"[a-zéèêàâîôûçï]{2,}\.\s+[A-ZÉÈ]|Commissaires|Conseil\b|Exploitation|Laveries|"
    r"d[eé]cortiquage|Concession|Redevances|statuts|Impr\.|impr\.|\[|\d|»|«|:|"
    r"\s[àa]\s+[A-Z]|[)(]",
)


# Leading matter the parser dragged in ahead of the real name: a commodity or
# place from a directory line ("oeufs. Meknes. David A. Benchimol"), a list
# label ("Conseil: MM. ..."), or an expanded honorific ("S. Exc. Hadj ...").
LEADING_SEGMENT = re.compile(
    r"^(?:.*?\b(?:conseil|commissaires?|adm|administrateurs?)\s*:\s*(?:MM\.|M\.)?\s*)|"
    r"^[^.]{2,40}\.\s+(?=[A-ZÉÈ])",
    re.I,
)
HONORIFIC_EXPANSION = re.compile(
    r"^(?:s\.?\s*exc(?:el)?\.?\s*|son\s+excellence\s+|l['’]amin\s+|le\s+pacha\s+)",
    re.I,
)


def recover_name(name: str) -> str:
    """Strip leading prose the parser captured ahead of a real name.

    Indigenous names are over-represented in polluted rows - the honorific
    register ("S. Exc. Hadj Thami Glaoui") and the directory lines where
    Moroccan and Jewish merchants appear ("oeufs. Meknes. David A. Benchimol")
    both attract leading matter. Discarding those rows therefore biases the
    coding downwards and drops precisely the best-documented figures, so a
    recovery pass runs before the usability gate.
    """
    n = HONORIFIC_EXPANSION.sub("", name.strip()).strip()
    if name_is_usable(n):
        return n
    # Strip one leading segment at a time and stop the moment what remains is
    # name-shaped, so "oeufs. Meknes. David A. Benchimol" yields the full name
    # rather than being stripped down to "Benchimol".
    for _ in range(6):
        m = LEADING_SEGMENT.match(n)
        if not m or m.end() >= len(n):
            break
        n = HONORIFIC_EXPANSION.sub("", n[m.end():].strip()).strip()
        if name_is_usable(n):
            return n
    return n or name


def name_is_usable(name: str) -> bool:
    """False for rows where the parser captured prose rather than a name."""
    n = name.strip()
    if len(n) < 3 or len(n.split()) > 7:
        return False
    if NAME_ARTEFACT.search(n):
        return False
    if re.match(r"^[a-zéèêàâîôûçï]", n) and not NAME_LOWER_OK.match(n):
        return False
    return True


# --- group patterns ------------------------------------------------------
VIET_SUR = (
    r"(?:nguyen|tran|pham|huynh|hoang|vu|bui|dang|ngo|duong|truong|phan|vo|"
    r"dinh|cao|mai|luu|ly|lam|thai|quach|tang|trieu|chau|doan|ta|to)"
)
VIET_MID = (
    r"(?:van|thi|duc|ngoc|huu|xuan|quang|thanh|cong|ba|tan|khac|nhu|the|trong|"
    r"hong|kim|minh|phu|quoc|sy|tien|trung|viet|dinh|hoa|huy|khanh|tuan|dai)"
)
# Requires a Vietnamese surname AND a Vietnamese second syllable, or a
# hyphenated triple. A bare "Le X" or "Van X" is French or Dutch - see
# positionality_rules.md.
VIETNAMESE = re.compile(
    rf"^{VIET_SUR}[\s-]+{VIET_MID}\b|^{VIET_SUR}(?:[\s-]+\w+){{2}}$", re.I
)
MALAGASY = re.compile(
    r"^(?:rakoto|rabe|ratsi|randria|rasoa|razafi|ramana|andria|rahari|ravelo|"
    r"rajaon|ramaro|ratrimo)\w{4,}",  # a 4+ char stem: "Rabearivelo" yes, "Rabeau" no
    re.I,
)
MAGHREBI_HONORIFIC = re.compile(
    r"\b(?:si|sidi|hadj|el[\s-]hadj|cheikh|ca[iï]d|k[aä]id|bachagha|agha|"
    r"moulay|moulai|mouley|lalla|mokaddem)\b",
    re.I,
)
MAGHREBI_PARTICLE = re.compile(
    r"\b(?:ben|bel|bou|ould|a[iï]t)[\s-]+\w|(?:^|\s)el[\s-]+\w|\bel-\w", re.I
)
MAGHREBI_GIVEN = re.compile(
    r"\b(?:mohamed|mohammed|muhammad|ahmed|ahmad|omar|sa[iï]d|abdelkader|abdallah|"
    r"abdel\w*|larbi|kaddour|tayeb|slimane|brahim|ibrahim|mustapha|mustafa|"
    r"messaoud|belkacem|hocine|hassan|hussein|driss|idriss|rachid|tahar|salah|"
    r"mahmoud|youssef|yousef|kada|bachir|lakhdar|miloud|djillali|tidjani|tijani|"
    r"khalil|djelloul|sebti|allal|boubker|hammou|lahcen|mekki|zoubir)\b",
    re.I,
)
# "Ali" alone is also an Italian/Corsican surname fragment; require it to be a
# standalone token at the start, which is where the given name sits.
MAGHREBI_ALI = re.compile(r"^(?:ali)\b", re.I)

WEST_AFRICAN = re.compile(
    r"\b(?:diop|diagne|ndiaye|gueye|sarr|sow|diallo|cisse|traore|keita|coulibaly|"
    r"konate|camara|toure|sylla|bamba|ouattara|kone|diarra|dembele|sagna|thiam|"
    r"niang|seck|mbaye|badji|sonko|mbodj|ndour|guisse|samb|tall|kourouma)\b",
    re.I,
)
SYRO_LEBANESE = re.compile(
    r"\b(?:khoury|khouri|haddad|sursock|sabbagh|aoun|chiha|pharaon|trad|bustros|"
    r"tabet|edde|gemayel|naccache|corm|debbas|takla|zalzal|arida|dagher|nahas|"
    r"kettaneh|beyhum|chehab|tueni|salam|daouk|bassoul|asfar|zahar)\b",
    re.I,
)
OTTOMAN_EGYPTIAN = re.compile(
    r"\b(?:pacha|pasha|yeghen|nubar|afifi|maher|sirry|serry|badrawi|abboud|"
    r"chukri|sükrü|hakki|servet|sezai|edhem|hamdy|mudarris|zaghloul|rushdi|"
    r"tewfik|fouad|farouk|sabri|khalil bey|melhame)\b",
    re.I,
)
MAGHREBI_JEWISH = re.compile(
    r"\b(?:benchimol|bensimon|corcos|toledano|assouline|sebag|boccara|guez|"
    r"chemla|bessis|nataf|hayat|zerbib|smadja|attal|dahan|elmaleh|abitbol|"
    r"azoulay|bouhsira|amar|sarfati|bensoussan|benhaim|ohana|zermati)\b",
    re.I,
)
CHINESE_INDOCHINESE = re.compile(
    r"\b(?:hui[\s-]?bon[\s-]?hoa|quach dam|ban hap|chan yok lam|tang keng|"
    r"ma tuyen|wang tai|ly hoa|hip hoa)\b",
    re.I,
)
# An Ottoman or Egyptian rank granted to Europeans as well - never on its own
# evidence of origin. Used only to *withhold* a European default, not to code.
RANK_TITLE = re.compile(r"\b(?:bey|pacha|pasha|effendi)\b", re.I)


def has_region(regions: str, *keys: str) -> bool:
    r = regions.lower()
    return any(k.lower() in r for k in keys)


MAGHREB_AND_AFRICA = (
    "Maroc", "Alger", "Tunis", "occidentale", "equatoriale", "Madagascar", "Empire",
)


def code_person(name: str, regions: str, countries: str) -> tuple[str, str, str, str]:
    """Return (positionality, group, confidence, evidence) for one person."""
    n = na(name)
    ev: list[str] = []
    group = ""

    if VIETNAMESE.search(n) and has_region(regions, "Indochine"):
        ev.append("vietnamese_name_structure")
        group = "vietnamese"
    elif CHINESE_INDOCHINESE.search(n) and has_region(regions, "Indochine"):
        ev.append("chinese_indochinese_curated")
        group = "chinese_indochinese"
    elif MALAGASY.search(n) and has_region(regions, "Madagascar"):
        ev.append("malagasy_prefix")
        group = "malagasy"
    elif WEST_AFRICAN.search(n) and has_region(regions, "occidentale", "equatoriale", "Empire"):
        ev.append("west_african_surname")
        group = "west_african"
    elif MAGHREBI_JEWISH.search(n):
        # Checked before the Arabic rules: several of these surnames are also
        # Arabic, and the intermediate coding is the more careful one.
        ev.append("maghrebi_jewish_surname")
        group = "maghrebi_jewish"
    elif SYRO_LEBANESE.search(n):
        ev.append("levantine_surname")
        group = "syro_lebanese"
    else:
        maghreb = []
        if MAGHREBI_HONORIFIC.search(n):
            maghreb.append("maghrebi_honorific")
        if MAGHREBI_PARTICLE.search(n):
            maghreb.append("maghrebi_particle")
        if MAGHREBI_GIVEN.search(n) or MAGHREBI_ALI.search(n):
            maghreb.append("maghrebi_given_name")
        if maghreb and has_region(regions, *MAGHREB_AND_AFRICA):
            ev = maghreb
            group = "maghrebi_arab_berber"
        elif OTTOMAN_EGYPTIAN.search(n) and has_region(regions, "Proche", "Empire"):
            ev.append("ottoman_egyptian_name")
            group = "ottoman_egyptian"

    if not group:
        # No indigenous marker. In a corpus of French colonial boards that is
        # overwhelmingly a European, but it is inference from absence.
        note = "residual_no_indigenous_marker"
        if RANK_TITLE.search(n):
            # "Boinet Bey", "H. Naus bey" - Europeans in Egyptian service. The
            # title tells us nothing about origin, so confidence drops.
            return ("colonial", "european_unspecified", "low", note + ";holds_ottoman_rank")
        return ("colonial", "european_unspecified", "low", note)

    evidence = ";".join(ev)
    # Two independent markers is materially stronger than one.
    confidence = "high" if len(ev) >= 2 else "medium"

    if group in {"vietnamese", "chinese_indochinese", "malagasy", "west_african",
                 "maghrebi_arab_berber"}:
        return ("native", group, confidence, evidence)
    if group == "syro_lebanese":
        # Native only under the French mandate; elsewhere a local elite in a
        # state France did not rule.
        if "Syrie-Liban" in countries:
            return ("native", group, confidence, evidence)
        return ("local_non_french_elite", group, confidence, evidence)
    if group == "ottoman_egyptian":
        return ("local_non_french_elite", group, confidence, evidence)
    if group == "maghrebi_jewish":
        return ("intermediate", group, confidence, evidence)
    return ("unclassified", group, "low", evidence)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", action="store_true",
                    help="print every person coded as other than European")
    args = ap.parse_args()

    people = read_csv("persons_resolved.csv")
    affil = [r for r in read_csv("affiliations.csv") if r["company_key"] and r["person_key"]]
    resolution = {r["person_key"]: r["person_key_resolved"]
                  for r in read_csv("person_resolution.csv")}

    # Countries a person is observed in, for the mandate-vs-sovereign test.
    countries: dict[str, set[str]] = defaultdict(set)
    board_ties: dict[str, int] = Counter()
    periods: dict[str, set[str]] = defaultdict(set)
    for r in affil:
        pid = resolution.get(r["person_key"], r["person_key"])
        if r["country"]:
            countries[pid].add(r["country"])
        if r["role"] in BOARD_ROLES:
            board_ties[pid] += 1
        per = period_of(r["year"])
        if per:
            periods[pid].add(per)

    rows: list[dict] = []
    for p in people:
        pid = p["person_id"]
        raw_name = p["name_variants"].split("; ")[0]
        name = recover_name(raw_name)
        ctry = "; ".join(sorted(countries.get(pid, ())))
        if not name_is_usable(name):
            rows.append({
                "person_id": pid,
                "name": name,
                "name_as_parsed": raw_name,
                "positionality": "unclassified",
                "positionality_group": "unusable_name",
                "confidence": "",
                "evidence": "name_is_parse_artefact",
                "regions": p["regions"],
                "countries": ctry,
                "n_board_companies": p["n_board_companies"],
                "n_board_ties": board_ties.get(pid, 0),
                "first_year": p["first_year"],
                "last_year": p["last_year"],
            })
            continue
        pos, group, conf, ev = code_person(name, p["regions"], ctry)
        if name != raw_name:
            ev = (ev + ";name_recovered") if ev else "name_recovered"
        rows.append({
            "person_id": pid,
            "name": name,
            "name_as_parsed": raw_name,
            "positionality": pos,
            "positionality_group": group,
            "confidence": conf,
            "evidence": ev,
            "regions": p["regions"],
            "countries": ctry,
            "n_board_companies": p["n_board_companies"],
            "n_board_ties": board_ties.get(pid, 0),
            "first_year": p["first_year"],
            "last_year": p["last_year"],
        })

    write_csv("person_positionality.csv", rows,
              ["person_id", "name", "name_as_parsed", "positionality", "positionality_group",
               "confidence", "evidence", "regions", "countries",
               "n_board_companies", "n_board_ties", "first_year", "last_year"])

    # Every non-European coding, written out in full. At this scale (~200 rows)
    # the coding is small enough to be read and corrected by hand, which is a
    # better guarantee than any confidence score.
    review = [r for r in rows
              if r["positionality_group"] not in {"european_unspecified", "unusable_name"}]
    review.sort(key=lambda r: (r["positionality_group"], r["name"]))
    write_csv("positionality_review.csv", review,
              ["person_id", "name", "name_as_parsed", "positionality",
               "positionality_group", "confidence", "evidence", "regions",
               "countries", "n_board_companies", "n_board_ties",
               "first_year", "last_year"])

    # --- summary by territory -------------------------------------------
    by_pid = {r["person_id"]: r for r in rows}
    terr: dict[str, Counter] = defaultdict(Counter)
    terr_ties: dict[str, Counter] = defaultdict(Counter)
    for r in affil:
        pid = resolution.get(r["person_key"], r["person_key"])
        rec = by_pid.get(pid)
        if not rec or r["role"] not in BOARD_ROLES:
            continue
        key = r["country"] or r["region"] or "(unlabelled)"
        terr[key][rec["positionality"]] += 0  # ensure key exists
        terr_ties[key][rec["positionality"]] += 1
    # Distinct people per territory, not ties.
    seen: dict[str, set] = defaultdict(set)
    for r in affil:
        pid = resolution.get(r["person_key"], r["person_key"])
        rec = by_pid.get(pid)
        if not rec or r["role"] not in BOARD_ROLES:
            continue
        key = r["country"] or r["region"] or "(unlabelled)"
        if pid not in seen[key]:
            seen[key].add(pid)
            terr[key][rec["positionality"]] += 1

    summary = []
    for key, c in sorted(terr.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(c.values())
        non_eur = c["native"] + c["intermediate"] + c["local_non_french_elite"]
        summary.append({
            "territory": key,
            "n_board_members": total,
            "n_colonial": c["colonial"],
            "n_native": c["native"],
            "n_intermediate": c["intermediate"],
            "n_local_non_french_elite": c["local_non_french_elite"],
            "n_unclassified": c["unclassified"],
            "share_native": round(c["native"] / total, 4) if total else "",
            "share_non_european": round(non_eur / total, 4) if total else "",
            "n_board_ties_native": terr_ties[key]["native"],
        })
    write_csv("positionality_by_territory.csv", summary,
              ["territory", "n_board_members", "n_colonial", "n_native",
               "n_intermediate", "n_local_non_french_elite", "n_unclassified",
               "share_native", "share_non_european", "n_board_ties_native"])

    # --- report ----------------------------------------------------------
    dist = Counter(r["positionality"] for r in rows)
    total = len(rows)
    print("\npositionality of person nodes:", file=sys.stderr)
    for k, v in dist.most_common():
        print(f"  {k:26s} {v:6,}  ({100 * v / total:5.2f}%)", file=sys.stderr)
    groups = Counter(r["positionality_group"] for r in rows
                     if r["positionality_group"] not in {"european_unspecified", "unusable_name"})
    print("\n  non-European groups:", file=sys.stderr)
    for k, v in groups.most_common():
        print(f"    {k:26s} {v:5,}", file=sys.stderr)

    print("\n  share of board members with an indigenous name, by territory:", file=sys.stderr)
    for s in summary[:14]:
        if s["n_board_members"] < 40:
            continue
        print(f"    {s['share_native']:7.4f}  {s['n_native']:4d}/{s['n_board_members']:5d}"
              f"  {s['territory'][:42]}", file=sys.stderr)

    if args.candidates:
        print("\n--- every person coded as other than European ---", file=sys.stderr)
        for r in sorted(rows, key=lambda r: (r["positionality_group"], r["name"])):
            if r["positionality_group"] in {"european_unspecified", "unusable_name"}:
                continue
            print(f"  {r['positionality']:22s} {r['positionality_group']:22s} "
                  f"{r['confidence']:6s} {r['name'][:38]:40s} {r['countries'][:30]}",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
