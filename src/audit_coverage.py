"""Stage 23 - what the unread documents actually are, territory by territory.

    python3 src/audit_coverage.py
    python3 src/audit_coverage.py --sample 12   # rows to hand-check

    data/processed/coverage_by_territory.csv
    data/processed/coverage_silent_documents.csv

§4g brought Tunisia from the worst-covered territory to above the corpus
average, and the residue that still yielded nothing was written off in an
earlier draft of METHODOLOGY as books and honours lists. That was wrong: two
of those documents were career blocks, and chasing them produced a whole
genre (§4l). The lesson is not about Tunisia. It is that **"the rest is
unreadable" is a claim, and this repository states claims with a file behind
them.** This stage is that file.

It reads every document that carries usable text and yields no tie, and sorts
it by the *register* it is written in — the shape a parser would have to
recognise — so that the next person can see where the remaining evidence is
and, just as usefully, where it is not.

## The registers

`REGISTERS` below, tested in order; a document is filed under the first that
matches, and the per-register match counts are all kept so a document with
several can be re-sorted.

- **`board_list`** — a bare or punctuated board heading. This is what §4g and
  §4h read, so a silent document with one is a parser defect and the most
  valuable thing this audit can find.
- **`person_career`** — the person-anchored line register of §4l.
- **`apposition`** — `M. Honoré Dejean, directeur de la Société agricole de
  My-Duc`, a role and a firm in running prose. §4d reads this shape when it
  sits near a board list; these are the loose ones.
- **`certificate`** — `Un administrateur (à gauche) : Eugène Fournier`, the
  caption under a reproduced share certificate. One or two names, no dates.
- **`deed`** — notarial: `Aux termes d'un acte reçu par Me Bérenger, notaire à
  Saïgon`. Names founders and shareholders, in a register of its own.
- **`press`** — a compilation of newspaper cuttings, which is what most of the
  Indochina residue is. Arrival notices, tender results, election counts.
- **`no_signal`** — nothing above matched.

## What it found, and why that is the useful answer

The residue is **not** a large unread board seam. Of the silent documents,
`board_list` matches a handful and `apposition` 74 across the whole corpus,
while the bulk of the largest residue — Indochina's, which is 68% of all
unread characters — is `press`: newspaper compilations where `MM.` introduces
tender bidders and election counts, not directors. A parser that read `MM.`
lists as boards would manufacture thousands of false ties out of a cattle
show's jury.

That is worth having measured rather than assumed, in both directions. It says
where not to spend effort, and the `board_list` and `apposition` rows say
exactly where a small amount of effort still pays.

**This stage adds no ties and changes no network file.** It is a diagnostic.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import random
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
TEXT = os.path.join(ROOT, "data", "text")
BY_TERRITORY = os.path.join(PROC, "coverage_by_territory.csv")
SILENT = os.path.join(PROC, "coverage_silent_documents.csv")

MIN_CHARS = 200        # below this a document is a stub, not a silent document

_ROLE = (r"administrateur(?:[- ]délégué)?|président(?:[- ]directeur général)?"
         r"|vice-président|directeur(?: général)?|gérant|censeur"
         r"|commissaire aux comptes|fondateur")
_FIRM = (r"(?:la\s+|le\s+|l['’]\s*)?(?:Société|Sté|Cie|Compagnie|Banque"
         r"|Comptoirs?|Crédit|Établissements|Éts|Union|Plantations|Mines"
         r"|Manufacture|Charbonnages|Docks)")

# Order matters: the first match files the document. Board evidence outranks
# prose, and prose outranks the press compilations it is usually embedded in.
REGISTERS = [
    ("board_list", re.compile(
        r"(?im)^\s*(?:CONSEIL D['’]ADMINISTRATION|ADMINISTRATEURS?"
        r"|Conseil d['’]administration|COMMISSAIRES? AUX COMPTES"
        r"|Conseil de surveillance|CENSEURS?)\s*:?\s*$")),
    ("person_career", re.compile(
        r"(?m)^\s*(?:Ancien\s+)?(?:Administrateur|Président|Vice-président"
        r"|Directeur|Gérant|Censeur)\b[^\n]{0,14}\b(?:de|du|des|d['’])\s+")),
    ("apposition", re.compile(
        rf"\bM(?:onsieur)?\.?\s+(?:[A-ZÉÈ][\w éèêàçï'’-]{{2,40}}?)\s*,\s*"
        rf"(?:{_ROLE})\s+(?:de|du|des|d['’])\s*{_FIRM}", re.IGNORECASE)),
    ("certificate", re.compile(r"(?i)\bun\s+administrateur\b[^:\n]{0,40}:")),
    ("deed", re.compile(
        r"(?i)(?:aux termes d['’]un acte|par acte (?:reçu|sous seing)"
        r"|notaire à|Me\s+[A-ZÉ][\wéèê-]+,\s*notaire)")),
    ("press", re.compile(
        r"(?:L['’]Avenir du Tonkin|L['’]Écho annamite|Les Annales coloniales"
        r"|Le Courrier d['’]Haïphong|L['’]Éveil économique|La Dépêche coloniale"
        r"|Journal officiel|L['’]Information financière|Le Temps"
        r"|L['’]Extrême-Orient|La Tribune indochinoise|Le Figaro"
        r"|\(\s*\w[\w' ’-]{4,40},\s*\d{1,2}\s+\w+\s+1[89]\d\d\s*\))")),
]

# A crude count of `SURNAME (Forename)` and `Forename SURNAME` name forms,
# used only to say how much personal-name material a document holds.
NAME_FORM_RE = re.compile(
    r"\b[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ'’\-]{2,}\s*\([A-ZÉ][a-zéèêàï'’-]+"
    r"|\b[A-ZÉ][a-zéèêàï'’-]{2,}\s+[A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ'’\-]{3,}\b")


def load(name: str) -> list[dict]:
    with open(os.path.join(PROC, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_text(doc_id: str) -> str:
    path = os.path.join(TEXT, f"{doc_id}.txt.gz")
    if not os.path.exists(path):
        return ""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def tie_counts() -> Counter:
    """Ties per document, across every genre file that carries a `doc_id`."""
    import glob
    out: Counter = Counter()
    for path in sorted(glob.glob(os.path.join(PROC, "affiliations*.csv"))):
        with open(path, encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("doc_id"):
                    out[r["doc_id"]] += 1
    return out


def classify(text: str) -> tuple[str, dict[str, int]]:
    """`(register, per-register match counts)`."""
    counts = {name: len(rx.findall(text)) for name, rx in REGISTERS}
    for name, _rx in REGISTERS:
        if counts[name]:
            return name, counts
    return "no_signal", counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0,
                    help="print this many classified rows to hand-check")
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()

    docs = load("documents.csv")
    chars = {r["doc_id"]: int(r["n_chars"] or 0)
             for r in load("text_extraction.csv")}
    ties = tie_counts()

    per_territory: dict[str, dict] = defaultdict(
        lambda: Counter({"n_documents": 0, "n_with_tie": 0, "n_silent": 0,
                         "silent_chars": 0, "n_ties": 0}))
    silent_rows = []
    for d in docs:
        n = chars.get(d["doc_id"], 0)
        if n < MIN_CHARS:
            continue
        terr = d.get("country") or "(unfiled)"
        agg = per_territory[terr]
        agg["n_documents"] += 1
        got = ties.get(d["doc_id"], 0)
        agg["n_ties"] += got
        if got:
            agg["n_with_tie"] += 1
            continue
        agg["n_silent"] += 1
        agg["silent_chars"] += n
        text = read_text(d["doc_id"])
        register, counts = classify(text)
        agg[f"reg_{register}"] += 1
        silent_rows.append({
            "doc_id": d["doc_id"], "territory": terr,
            "entry_type": d.get("entry_type", ""),
            "name_listed": d.get("name_listed", "")[:120],
            "n_chars": n, "register": register,
            "n_name_forms": len(NAME_FORM_RE.findall(text)),
            **{f"n_{k}": v for k, v in counts.items()},
        })

    reg_names = [f"reg_{n}" for n, _ in REGISTERS] + ["reg_no_signal"]
    terr_rows = []
    for terr, agg in per_territory.items():
        row = {"territory": terr, "n_documents": agg["n_documents"],
               "n_with_tie": agg["n_with_tie"],
               "share_with_tie": f"{agg['n_with_tie'] / agg['n_documents']:.4f}",
               "n_ties": agg["n_ties"], "n_silent": agg["n_silent"],
               "silent_chars": agg["silent_chars"]}
        for r in reg_names:
            row[r] = agg[r]
        terr_rows.append(row)
    terr_rows.sort(key=lambda r: -r["n_silent"])

    with open(BY_TERRITORY, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(terr_rows[0]))
        w.writeheader()
        w.writerows(terr_rows)
    silent_rows.sort(key=lambda r: -r["n_chars"])
    with open(SILENT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(silent_rows[0]))
        w.writeheader()
        w.writerows(silent_rows)
    print(f"wrote {os.path.relpath(BY_TERRITORY, ROOT)}: {len(terr_rows)} territories",
          file=sys.stderr)
    print(f"wrote {os.path.relpath(SILENT, ROOT)}: {len(silent_rows):,} documents",
          file=sys.stderr)

    total = sum(r["n_documents"] for r in terr_rows)
    with_tie = sum(r["n_with_tie"] for r in terr_rows)
    print(f"\n{with_tie:,}/{total:,} documents with usable text yield a tie "
          f"({100 * with_tie / total:.1f}%); {len(silent_rows):,} silent, "
          f"{sum(r['n_chars'] for r in silent_rows):,} characters",
          file=sys.stderr)
    reg = Counter(r["register"] for r in silent_rows)
    print("\nthe silent residue, by register:", file=sys.stderr)
    for name, n in reg.most_common():
        share = 100 * n / len(silent_rows)
        cs = sum(r["n_chars"] for r in silent_rows if r["register"] == name)
        print(f"  {name:15} {n:5} docs ({share:4.1f}%)  {cs:12,} chars",
              file=sys.stderr)
    print("\nworst-covered territories with 25+ documents:", file=sys.stderr)
    worst = sorted((r for r in terr_rows if r["n_documents"] >= 25),
                   key=lambda r: float(r["share_with_tie"]))[:6]
    for r in worst:
        print(f"  {r['territory'][:32]:34} {100 * float(r['share_with_tie']):5.1f}% "
              f"of {r['n_documents']:5} docs, {r['n_silent']:5} silent",
              file=sys.stderr)

    if args.sample:
        random.seed(args.seed)
        print(f"\n--- {args.sample} silent documents to hand-check ---",
              file=sys.stderr)
        for r in random.sample(silent_rows, min(args.sample, len(silent_rows))):
            print(f"\n  [{r['register']}] {r['territory']} · {r['n_chars']:,} chars "
                  f"· {r['n_name_forms']} name forms", file=sys.stderr)
            print(f"    {r['name_listed'][:90]}", file=sys.stderr)


if __name__ == "__main__":
    main()
