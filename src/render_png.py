"""Stage 9 - rasterise every figure to PNG, one network per file.

    python3 src/render_png.py                 # every SVG under figures/
    python3 src/render_png.py --scale 3       # for print
    python3 src/render_png.py --lang en       # just the English tree
    python3 src/render_png.py --only algerie tunisie

Each `<name>.svg` becomes `<name>.png` beside it, so the pair is always
together. Rendering goes through headless Chromium rather than a converter
library because the figures are laid out against Chromium's text metrics: the
label-fitting constant in `make_figures._text_width` was calibrated against
`getComputedTextLength` in this browser, and another rasteriser's font
substitution would move labels the checks have already verified.

The scale factor multiplies the SVG's own pixel size, so `--scale 2` on a
1500x1000 figure gives 3000x2000 - retina-sharp on screen, and enough for a
figure printed a page wide. The PNGs are versioned alongside the SVGs (11 MB
for all 47) because GitHub previews them inline where it will not render a
1 MB SVG, and because the point of a raster is that it opens anywhere.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG_DIR = os.path.join(ROOT, "figures")

# The environment pre-installs Chromium and tells Playwright where it is;
# the pinned browser build a `playwright install` would fetch is absent, so
# the executable path is passed explicitly.
CHROMIUM = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")

SIZE_RE = re.compile(r'<svg[^>]*?\bwidth="([\d.]+)"[^>]*?\bheight="([\d.]+)"')


def svg_size(path: str) -> tuple[int, int]:
    """Intrinsic size, so the raster is the figure and nothing else."""
    with open(path, encoding="utf-8") as fh:
        head = fh.read(2000)
    m = SIZE_RE.search(head)
    if not m:
        raise SystemExit(f"{path}: no width/height on the root <svg>")
    return round(float(m.group(1))), round(float(m.group(2)))


def figures(only: list[str] | None, lang: str = "all") -> list[str]:
    # Recursive, so figures/en/ and figures/en/by_country/ are picked up
    # without a second list to keep in step with the figure scripts.
    paths = sorted(glob.glob(os.path.join(FIG_DIR, "**", "*.svg"), recursive=True))
    if lang == "fr":
        paths = [p for p in paths if os.sep + "en" + os.sep not in p]
    elif lang == "en":
        paths = [p for p in paths if os.sep + "en" + os.sep in p]
    if only:
        wanted = {o.lower().removesuffix(".svg") for o in only}
        paths = [p for p in paths
                 if os.path.basename(p)[:-4].lower() in wanted
                 or any(w in os.path.basename(p).lower() for w in wanted)]
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=2.0,
                    help="pixel ratio; 2 is good on screen, 3 for print")
    ap.add_argument("--only", nargs="*", help="render just these (by file stem)")
    ap.add_argument("--lang", choices=("all", "fr", "en"), default="all",
                    help="restrict to one language tree")
    args = ap.parse_args()

    paths = figures(args.only, args.lang)
    if not paths:
        raise SystemExit("no matching SVGs in figures/")

    from playwright.sync_api import sync_playwright

    total = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROMIUM)
        for path in paths:
            w, h = svg_size(path)
            page = browser.new_page(viewport={"width": w, "height": h},
                                    device_scale_factor=args.scale)
            page.goto(f"file://{path}")
            page.wait_for_timeout(60)
            out = path[:-4] + ".png"
            # Not full_page: on a bare SVG document Chromium's full-page
            # capture waits on a layout that never settles.
            page.screenshot(path=out)
            page.close()
            total += os.path.getsize(out)
            print(f"{os.path.relpath(out, ROOT)}  "
                  f"{int(w * args.scale)}x{int(h * args.scale)}  "
                  f"{os.path.getsize(out) / 1e6:.2f} MB", file=sys.stderr)
        browser.close()

    print(f"\n{len(paths)} PNGs, {total / 1e6:.1f} MB total", file=sys.stderr)


if __name__ == "__main__":
    main()
