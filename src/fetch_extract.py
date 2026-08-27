"""Stage 2 - download each catalogued PDF and extract its text layer.

The PDFs are large (~45 GB in total, up to 44 MB each) because they embed
scanned page images alongside the publisher's keyed transcription. Only the
text is needed, so each PDF is streamed into memory, decoded, and discarded
without ever being written to disk. The extracted text is stored gzipped
(~10x smaller) under data/text/.

PyMuPDF is required. The PDFs embed subsetted Type1 fonts with MacRoman
encodings; pypdf and pdfminer both decode them into a monotonic substitution
cipher ("Publie le" comes out as "«uelieHle"), whereas PyMuPDF resolves the
font encoding correctly. Any change of extraction backend must be validated
against src/checks.py.

Pages are joined with a form feed (\\x0c) so that later stages can report the
page a claim came from.

Usage
    python3 src/fetch_extract.py               # all documents, resumable
    python3 src/fetch_extract.py --limit 50    # smoke test
    python3 src/fetch_extract.py --workers 8
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ensure_dir, fetch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC_DIR = os.path.join(ROOT, "data", "processed")
TEXT_DIR = os.path.join(ROOT, "data", "text")
META_PATH = os.path.join(PROC_DIR, "text_extraction.csv")

PAGE_SEP = "\x0c"

META_FIELDS = [
    "doc_id",
    "pdf_url",
    "status",
    "http_bytes",
    "sha256",
    "n_pages",
    "n_chars",
    "n_pages_with_text",
    "pdf_title",
    "pdf_creation_date",
    "error",
]

_lock = threading.Lock()
_counter = {"done": 0, "ok": 0, "fail": 0, "bytes": 0}


def text_path(doc_id: str) -> str:
    return os.path.join(TEXT_DIR, f"{doc_id}.txt.gz")


def extract_one(doc_id: str, pdf_url: str) -> dict:
    """Fetch one PDF and write its text. Returns a metadata row."""
    row = {f: "" for f in META_FIELDS}
    row["doc_id"] = doc_id
    row["pdf_url"] = pdf_url
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PyMuPDF is required (pip install pymupdf); other PDF backends "
            "mis-decode this site's font encodings."
        ) from exc

    try:
        data = fetch(pdf_url)
    except Exception as exc:  # noqa: BLE001
        row["status"] = "fetch_error"
        row["error"] = str(exc)[:300]
        return row

    row["http_bytes"] = len(data)
    row["sha256"] = hashlib.sha256(data).hexdigest()

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        row["status"] = "open_error"
        row["error"] = str(exc)[:300]
        return row

    try:
        pages = []
        with_text = 0
        for page in doc:
            t = page.get_text()
            if t and t.strip():
                with_text += 1
            pages.append(t or "")
        meta = doc.metadata or {}
        row["n_pages"] = doc.page_count
        row["pdf_title"] = (meta.get("title") or "")[:200]
        row["pdf_creation_date"] = (meta.get("creationDate") or "")[:40]
    except Exception as exc:  # noqa: BLE001
        row["status"] = "extract_error"
        row["error"] = str(exc)[:300]
        return row
    finally:
        doc.close()
        del data

    body = PAGE_SEP.join(pages)
    row["n_chars"] = len(body)
    row["n_pages_with_text"] = with_text
    # A PDF whose text layer is missing entirely is flagged rather than dropped,
    # so that coverage gaps are visible in the dataset instead of silent.
    row["status"] = "ok" if with_text else "no_text_layer"

    tmp = text_path(doc_id) + ".part"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(tmp, text_path(doc_id))
    return row


def load_existing_meta() -> dict[str, dict]:
    if not os.path.exists(META_PATH):
        return {}
    with open(META_PATH, encoding="utf-8", newline="") as fh:
        return {r["doc_id"]: r for r in csv.DictReader(fh)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="process at most N documents")
    ap.add_argument("--retry-failed", action="store_true", help="re-attempt previous failures")
    args = ap.parse_args()

    ensure_dir(TEXT_DIR)
    ensure_dir(PROC_DIR)

    with open(os.path.join(PROC_DIR, "documents.csv"), encoding="utf-8", newline="") as fh:
        docs = [(r["doc_id"], r["pdf_url"]) for r in csv.DictReader(fh)]

    meta = load_existing_meta()
    todo = []
    for doc_id, url in docs:
        prev = meta.get(doc_id)
        have_text = os.path.exists(text_path(doc_id))
        if prev and prev.get("status") in {"ok", "no_text_layer"} and have_text:
            continue
        if prev and not args.retry_failed and not have_text and prev.get("status") == "http_404":
            continue
        todo.append((doc_id, url))

    pending = len(todo)
    if args.limit:
        todo = todo[: args.limit]

    total = len(todo)
    print(
        f"{len(docs)} catalogued, {len(docs) - pending} already extracted, "
        f"{pending} pending, {total} to do this run",
        file=sys.stderr,
    )
    if not total:
        return

    started = time.time()
    results: list[dict] = []

    def work(item: tuple[str, str]) -> None:
        doc_id, url = item
        row = extract_one(doc_id, url)
        with _lock:
            results.append(row)
            _counter["done"] += 1
            _counter["bytes"] += int(row["http_bytes"] or 0)
            if row["status"] in {"ok", "no_text_layer"}:
                _counter["ok"] += 1
            else:
                _counter["fail"] += 1
            n = _counter["done"]
            if n % 50 == 0 or n == total:
                el = time.time() - started
                gb = _counter["bytes"] / 1e9
                rate = n / el if el else 0
                eta = (total - n) / rate / 60 if rate else 0
                print(
                    f"  {n}/{total} ok={_counter['ok']} fail={_counter['fail']} "
                    f"{gb:.1f}GB {rate:.1f}/s eta {eta:.0f}min",
                    file=sys.stderr,
                    flush=True,
                )

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))

    for row in results:
        meta[row["doc_id"]] = row

    tmp = META_PATH + ".part"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=META_FIELDS, extrasaction="ignore")
        w.writeheader()
        for doc_id, _ in docs:
            if doc_id in meta:
                w.writerow(meta[doc_id])
    os.replace(tmp, META_PATH)

    from collections import Counter

    print("\nstatus:", Counter(r["status"] for r in meta.values()), file=sys.stderr)
    print(f"wrote {META_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
