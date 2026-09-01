"""The world basemap: land from a shapefile, and a Robinson projection.

Used by the map figures (stages 10 and 21). Two things live here because both
are cartography rather than analysis, and because every map figure has to agree
about them or the panels stop being comparable.

**The land.** `data/reference/world_land.geojson`, built once by
`fetch_basemap.py` from Natural Earth's `ne_50m_land` shapefile and checked in,
so drawing a map needs no network. Coastline only: no borders, because a modern
border drawn over a corpus that runs from the 1870s to the 1970s would be an
anachronism, and no rivers or lakes, because they would compete with the edges
for the reader's attention while carrying nothing about the network.

**The projection is Robinson.** Plate carree, which the first version of these
figures used, is the projection you get by not choosing one: it stretches
Scandinavia to the width of the Sahara and leaves a 320-degree canvas looking
like a wall chart. Robinson is the compromise the discipline settled on for
world maps that are looked at rather than measured on - meridians curve, the
high latitudes are pulled in, and the result reads as a globe. It is
tabulated, not analytic, and only the forward direction is needed here.

Distances are **not** measured on the projection. `place_on_map.haversine`
works on the sphere, so the kilometre figures in the captions are independent
of how the map is drawn.
"""

from __future__ import annotations

import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAND = os.path.join(ROOT, "data", "reference", "world_land.geojson")

# Robinson's table, every five degrees: the relative length of the parallel and
# its distance from the equator. Interpolated linearly, which at five-degree
# steps is well under a pixel at any size these figures are drawn.
_TABLE = [
    (0, 1.0000, 0.0000), (5, 0.9986, 0.0620), (10, 0.9954, 0.1240),
    (15, 0.9900, 0.1860), (20, 0.9822, 0.2480), (25, 0.9730, 0.3100),
    (30, 0.9600, 0.3720), (35, 0.9427, 0.4340), (40, 0.9216, 0.4958),
    (45, 0.8962, 0.5571), (50, 0.8679, 0.6176), (55, 0.8350, 0.6769),
    (60, 0.7986, 0.7346), (65, 0.7597, 0.7903), (70, 0.7186, 0.8435),
    (75, 0.6732, 0.8936), (80, 0.6213, 0.9394), (85, 0.5722, 0.9761),
    (90, 0.5322, 1.0000),
]
_KX = 0.8487
_KY = 1.3523


def _interp(lat: float) -> tuple[float, float]:
    a = min(abs(lat), 90.0)
    i = min(int(a // 5), len(_TABLE) - 2)
    lo, xlo, ylo = _TABLE[i]
    _hi, xhi, yhi = _TABLE[i + 1]
    t = (a - lo) / 5.0
    x = xlo + t * (xhi - xlo)
    y = ylo + t * (yhi - ylo)
    return x, (y if lat >= 0 else -y)


class Robinson:
    """Forward Robinson, fitted to a width and a latitude window.

    The latitude window is the honest way to crop a world map: the corpus has
    nothing below 46 south or above 61 north, and drawing Antarctica and the
    Canadian Arctic at full height would spend a third of the canvas on ocean
    and ice to no purpose. Longitude is never cropped - the network reaches
    from Tahiti to Shanghai.
    """

    def __init__(self, width: float, pad: float = 0.0,
                 lat_min: float = -58.0, lat_max: float = 74.0,
                 lon_min: float = -180.0, lon_max: float = 180.0):
        self.pad = pad
        self.width = width
        self.lat_min, self.lat_max = lat_min, lat_max
        self.lon_min, self.lon_max = lon_min, lon_max
        x0 = self._raw_x(lon_min, 0.0)
        x1 = self._raw_x(lon_max, 0.0)
        self.scale = (width - 2 * pad) / (x1 - x0)
        self._x0 = x0
        _, y_top = _interp(lat_max)
        _, y_bot = _interp(lat_min)
        self._y_top = _KY * y_top
        self.height = _KY * (y_top - y_bot) * self.scale + 2 * pad

    def _raw_x(self, lon: float, lat: float) -> float:
        x, _ = _interp(lat)
        return _KX * math.radians(lon) * x

    def project(self, lat: float, lon: float) -> tuple[float, float]:
        x, y = _interp(lat)
        px = self.pad + (_KX * math.radians(lon) * x - self._x0) * self.scale
        py = self.pad + (self._y_top - _KY * y) * self.scale
        return px, py

    def meridian(self, lon: float, step: float = 4.0) -> str:
        """One meridian as an SVG path. Curved, which is the point of Robinson."""
        pts = []
        lat = self.lat_min
        while lat <= self.lat_max + 1e-9:
            pts.append(self.project(lat, lon))
            lat += step
        return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts)

    def parallel(self, lat: float) -> str:
        (x1, y1) = self.project(lat, self.lon_min)
        (x2, y2) = self.project(lat, self.lon_max)
        return f"M{x1:.1f} {y1:.1f}L{x2:.1f} {y2:.1f}"


_land_cache: list | None = None


def land_rings() -> list:
    """The land polygons, lazily read once per process."""
    global _land_cache
    if _land_cache is None:
        if not os.path.exists(LAND):
            raise SystemExit("run: python3 src/fetch_basemap.py")
        with open(LAND, encoding="utf-8") as fh:
            _land_cache = json.load(fh)["geometry"]["coordinates"]
    return _land_cache


def land_path(proj: Robinson) -> str:
    """Every land ring as one path `d`, clipped crudely to the frame.

    A ring wholly outside the latitude window is skipped; one that straddles
    the edge is drawn and left to the clip path, because clipping a polygon
    properly means reconstructing its boundary along the frame and the frame
    is already there.
    """
    out = []
    lat_lo, lat_hi = proj.lat_min - 2, proj.lat_max + 2
    for poly in land_rings():
        for ring in poly:
            lats = [p[1] for p in ring]
            if max(lats) < lat_lo or min(lats) > lat_hi:
                continue
            pts = [proj.project(lat, lon) for lon, lat in ring]
            out.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z")
    return "".join(out)


def basemap_svg(proj: Robinson, palette: dict, clip_id: str,
                dy: float = 0.0, meridian_step: int = 30,
                parallel_step: int = 20, labels: bool = True) -> str:
    """Land, graticule and frame — everything under the data.

    Order matters: land fill, then graticule over it (a grid under the land is
    invisible on the continents and present on the ocean, which reads as an
    error), then the frame, then the data on top.
    """
    p = palette
    inner = proj.height - 2 * proj.pad
    frame = (f'<rect x="{proj.pad:.1f}" y="{proj.pad + dy:.1f}" '
             f'width="{proj.width - 2 * proj.pad:.1f}" height="{inner:.1f}"/>')
    out = [f'<clipPath id="{clip_id}">{frame}</clipPath>',
           f'<g clip-path="url(#{clip_id})" transform="translate(0 {dy:.1f})">',
           f'<path d="{land_path(proj)}" fill="{p["land"]}" '
           f'stroke="{p["coast"]}" stroke-width="0.7" fill-rule="evenodd"/>']

    grid = []
    lon = -180
    while lon <= 180:
        grid.append(proj.meridian(lon))
        lon += meridian_step
    lat = -80
    while lat <= 80:
        if proj.lat_min <= lat <= proj.lat_max:
            grid.append(proj.parallel(lat))
        lat += parallel_step
    out.append(f'<path d="{"".join(grid)}" fill="none" stroke="{p["graticule"]}" '
               f'stroke-width="0.6"/>')
    out.append("</g>")
    out.append(f'<g fill="none" stroke="{p["hairline"]}" stroke-width="1">'
               f'{frame}</g>')

    if labels:
        out.append(_graticule_labels(proj, p, dy, meridian_step, parallel_step))
    return "".join(out)


def _graticule_labels(proj, p, dy, meridian_step, parallel_step) -> str:
    """Degrees along the frame, not across the map.

    On a curved projection a label sitting on its meridian in mid-ocean has to
    be rotated to sit right, and unrotated it looks like a mistake. Along the
    frame it needs no rotation and stays out of the data.
    """
    font = 9.0
    out = [f'<g font-size="{font}" font-family="ui-sans-serif,system-ui,sans-serif" '
           f'fill="{p["text_muted"]}">']
    lon = -180 + meridian_step
    while lon <= 180 - meridian_step:
        x, y = proj.project(proj.lat_min, lon)
        hand = "E" if lon > 0 else ("W" if lon < 0 else "")
        out.append(f'<text x="{x:.1f}" y="{y + dy + font + 3:.1f}" '
                   f'text-anchor="middle">{abs(lon)}°{hand}</text>')
        lon += meridian_step
    lat = -80
    while lat <= 80:
        if proj.lat_min + 4 <= lat <= proj.lat_max - 4:
            # A fixed column just outside the frame, not the parallel's own
            # left end: on Robinson a parallel is shorter than the equator, so
            # a label pinned to its end drifts inward as latitude rises and
            # ends up sitting in the middle of Canada.
            _, y = proj.project(lat, proj.lon_min)
            hand = "N" if lat > 0 else ("S" if lat < 0 else "")
            out.append(f'<text x="{proj.pad - 5:.1f}" '
                       f'y="{y + dy + font * 0.36:.1f}" '
                       f'text-anchor="end">{abs(lat)}°{hand}</text>')
        lat += parallel_step
    out.append("</g>")
    return "".join(out)
