"""Stage 0b - build the world basemap from the Natural Earth shapefile.

    python3 src/fetch_basemap.py                 # writes data/reference/world_land.geojson
    python3 src/fetch_basemap.py --scale 110m    # the coarser cut
    python3 src/fetch_basemap.py --tolerance 0.1 # more aggressive simplification

Until now the map figures carried the geography on a graticule alone, on the
grounds that no basemap shipped with the repository. That was a constraint
inherited from figure 7 rather than a reasoned one, and a world map without
coastlines is a scatter plot wearing a compass. This stage fetches the
coastline once, simplifies it, and checks the result into
`data/reference/world_land.geojson`, so every later run is offline and every
figure draws the same land.

**Source.** Natural Earth `ne_50m_land`, from the project's own CDN. Natural
Earth is in the **public domain** — the project asks for credit and imposes no
conditions — and it is the canonical basemap for cartography at this scale.

**The shapefile is read directly, with no GIS dependency.** `pyshp`,
`geopandas` and `fiona` are not installed and are not worth adding for one
layer of polygons: the `.shp` format is a documented sequence of little-endian
doubles and forty lines read it. The alternative — trusting a third party's
GeoJSON conversion of the same data — swaps a small amount of code for an
unverifiable provenance chain.

**Land only, and no borders.** The corpus runs from the 1870s to the 1970s and
a modern border drawn across it would be an anachronism: the whole point of
these figures is that Dakar and Brazzaville were administered from Paris.
Coastlines have barely moved at this scale, so the coastline is safe and the
borders are omitted. Rivers and lakes are omitted too — they carry no
information about the interlock network and would compete with the edges.

**Simplification is Douglas-Peucker, and the tolerance is per ring.** A flat
tolerance is what a first pass does and it deletes the empire: at 0.15 degrees
Tahiti, Guadeloupe and Saint-Pierre are each smaller than the tolerance, so
Douglas-Peucker reduces them to two points and they vanish - leaving an anchor
disc and a label floating on blank ocean. So each ring gets
`min(TOLERANCE, RING_FRACTION * sqrt(area))`: continents are simplified hard,
an island is simplified in proportion to itself.

Rings below `MIN_AREA` are dropped instead. At 1,560 pixels for 320 degrees of
longitude a ring of 0.008 square degrees is about a third of a pixel across, so
this removes only what could not be seen; the places that matter are carried by
their anchor disc regardless. Coordinates are rounded to two decimals, which is
1.1 km at the equator and a twentieth of a pixel.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import struct
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "reference", "world_land.geojson")
URL = "https://naciscdn.org/naturalearth/{scale}/physical/ne_{scale}_land.zip"

SHAPE_POLYGON = 5
DEFAULT_TOLERANCE = 0.12   # degrees, for a continent-sized ring
RING_FRACTION = 0.2        # of sqrt(area): the tolerance a small island gets
MIN_AREA = 0.008           # square degrees; below this a ring is sub-pixel
DEFAULT_PRECISION = 2      # decimals; 0.01 deg is ~1.1 km
MIN_RING = 4               # points, after simplification


def read_shp_polygons(blob: bytes) -> list[list[list[tuple[float, float]]]]:
    """Every polygon in a shapefile, as a list of rings of (lon, lat).

    Only shape type 5 (polygon) is handled, which is all `ne_*_land` contains.
    The format: a 100-byte header, then records of an 8-byte big-endian header
    followed by little-endian content. A polygon's content is a bounding box,
    a part count, a point count, the index in the point array where each ring
    starts, and then the points.
    """
    code, = struct.unpack_from(">i", blob, 0)
    if code != 9994:
        raise SystemExit(f"not a shapefile: file code {code}")
    shape_type, = struct.unpack_from("<i", blob, 32)
    if shape_type != SHAPE_POLYGON:
        raise SystemExit(f"expected polygons (5), got shape type {shape_type}")

    out = []
    pos = 100
    end = len(blob)
    while pos < end:
        _num, words = struct.unpack_from(">ii", blob, pos)
        content = pos + 8
        rec_type, = struct.unpack_from("<i", blob, content)
        if rec_type == SHAPE_POLYGON:
            n_parts, n_points = struct.unpack_from("<ii", blob, content + 36)
            parts = struct.unpack_from(f"<{n_parts}i", blob, content + 44)
            base = content + 44 + 4 * n_parts
            xy = struct.unpack_from(f"<{2 * n_points}d", blob, base)
            rings = []
            for i, start in enumerate(parts):
                stop = parts[i + 1] if i + 1 < n_parts else n_points
                rings.append([(xy[2 * j], xy[2 * j + 1]) for j in range(start, stop)])
            out.append(rings)
        pos = content + words * 2
    return out


def simplify(points: list[tuple[float, float]], tol: float):
    """Douglas-Peucker, iterative so a 4,000-point ring cannot blow the stack."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        x1, y1 = points[a]
        x2, y2 = points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = dx * dx + dy * dy
        worst, at = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if norm == 0.0:
                d = (px - x1) ** 2 + (py - y1) ** 2
            else:
                # Perpendicular distance, squared and unnormalised until the end.
                d = abs(dy * (px - x1) - dx * (py - y1)) ** 2 / norm
            if d > worst:
                worst, at = d, i
        if worst > tol * tol:
            keep[at] = True
            stack.append((a, at))
            stack.append((at, b))
    return [p for p, k in zip(points, keep) if k]


def ring_area(ring) -> float:
    """The shoelace area in square degrees. Sign discarded: only size is used."""
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def build(blob: bytes, tol: float, precision: int,
          min_area: float = MIN_AREA) -> dict:
    polygons = read_shp_polygons(blob)
    raw_points = sum(len(r) for poly in polygons for r in poly)
    coords = []
    kept_points = 0
    dropped = 0
    for poly in polygons:
        rings = []
        for ring in poly:
            area = ring_area(ring)
            if area < min_area:
                dropped += 1
                continue
            # Per-ring tolerance, so an island is not simplified out of
            # existence by a tolerance chosen for Eurasia.
            small = simplify(ring, min(tol, RING_FRACTION * math.sqrt(area)))
            if len(small) < MIN_RING:
                dropped += 1
                continue
            if small[0] != small[-1]:
                small.append(small[0])
            rings.append([[round(x, precision), round(y, precision)]
                          for x, y in small])
            kept_points += len(small)
        if rings:
            coords.append(rings)
    return {
        "type": "Feature",
        "properties": {
            "name": "Natural Earth land",
            "source": "Natural Earth, ne_*_land (public domain)",
            "simplified_degrees": tol,
            "precision_decimals": precision,
            "polygons": len(coords),
            "rings_dropped_as_subpixel": dropped,
            "min_area_sq_degrees": min_area,
            "points": kept_points,
            "points_before_simplification": raw_points,
        },
        "geometry": {"type": "MultiPolygon", "coordinates": coords},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="50m", choices=["10m", "50m", "110m"])
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    ap.add_argument("--precision", type=int, default=DEFAULT_PRECISION)
    ap.add_argument("--min-area", type=float, default=MIN_AREA)
    ap.add_argument("--zip", help="a local copy of the Natural Earth archive")
    args = ap.parse_args()

    if args.zip:
        data = open(args.zip, "rb").read()
    else:
        url = URL.format(scale=args.scale)
        print(f"fetching {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=120) as fh:
            data = fh.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.endswith(".shp"))
        blob = z.read(name)
    print(f"read {name}: {len(blob):,} bytes", file=sys.stderr)

    feature = build(blob, args.tolerance, args.precision, args.min_area)
    feature["properties"]["scale"] = args.scale
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(feature, fh, separators=(",", ":"))
        fh.write("\n")
    p = feature["properties"]
    print(f"wrote {os.path.relpath(OUT, ROOT)}: {p['polygons']:,} polygons, "
          f"{p['points']:,} points (from {p['points_before_simplification']:,}), "
          f"{os.path.getsize(OUT) / 1024:.0f} KB", file=sys.stderr)


if __name__ == "__main__":
    main()
