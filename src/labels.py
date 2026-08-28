"""English labels for the French categories the source uses.

The dataset is built from a French-language collection, so its territory,
region and sector values are French as printed. `data/reference/labels_en.csv`
maps all 183 of them to English, and this module is the lookup.

**Company and person names are deliberately not translated.** *Banque de
l'Indochine* is the firm's legal name, not a description of it; an English
"Bank of Indochina" would be a name that never existed and could not be looked
up in any archive or authority file. The same holds for people. What gets
translated here is the classification vocabulary — the words the compiler used
to file things — because that is a description and a reader needs it.

Territory names are the exception worth stating: *Maroc* → *Morocco* and
*Afrique occidentale française* → *French West Africa* are the standard forms
in English-language scholarship on the same subject, so leaving them French
would be the odd choice rather than the faithful one.
"""

from __future__ import annotations

import csv
import functools
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS_PATH = os.path.join(ROOT, "data", "reference", "labels_en.csv")

LANGS = ("fr", "en")


@functools.lru_cache(maxsize=1)
def _tables() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not os.path.exists(LABELS_PATH):
        return out
    with open(LABELS_PATH, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["kind"], {})[row["source_fr"]] = row["english"]
    return out


def to_en(value: str, kind: str = "territory") -> str:
    """English label for one source value, or the value itself if unmapped.

    Falling back to the source string rather than raising is deliberate: a
    figure with one untranslated territory is a small blemish, a figure that
    fails to build because the source added a heading is an outage. `checks.py`
    asserts the table is complete, so a gap is caught there instead.
    """
    return _tables().get(kind, {}).get(value, value)


def localise(value: str, lang: str, kind: str = "territory") -> str:
    return to_en(value, kind) if lang == "en" else value


def coverage(values, kind: str = "territory") -> list[str]:
    """Source values of `kind` with no English label. Used by checks.py."""
    table = _tables().get(kind, {})
    return sorted({v for v in values if v and v not in table})
