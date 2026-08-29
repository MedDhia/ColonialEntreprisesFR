"""Node-level drawing primitives.

`make_figures.draw_network` was written for the big pictures — a 170-firm core,
a 3,000-firm hairball, 42 territory graphs — where the unit of reading is the
shape of the whole. It draws straight hairlines, one edge colour, and stacks
its labels down the margins with leader lines, because at that density there is
no free canvas beside a node and no useful distinction between one edge and
another.

This module is for the other case: a graph small enough that the unit of
reading is the individual node. Fifty firms you can name, forty-six nodes of a
two-mode graph, eighty firms on a line. Different job, different primitives:

- **Curved edges.** Straight segments between scattered nodes produce a moiré
  of near-parallel lines and every crossing looks like a node. A quadratic
  bezier with a consistent bow separates edges that share endpoints and makes
  crossings read as crossings.
- **Edges that carry a category.** In the big figures an edge is an edge. Here
  "this tie crosses a colonial border" is often the finding, so an edge can
  take a hue — one categorical slot against the recessive grey, never a ramp.
- **Labels on the node, with a halo.** A label in the margin needs a leader
  line and forces the reader to trace it. Placed beside its node it does not,
  provided it stays legible over whatever it covers: `paint-order="stroke"`
  with a surface-coloured stroke gives every glyph a 3px moat, which is what
  makes in-place labelling possible over edges at all.
- **Layouts that mean something.** A spring layout means "connected things are
  near each other" and nothing more. Rings by k-core, positions by territory
  along an axis, two columns for a two-mode graph — each puts a variable on the
  canvas that the force layout would have scrambled.

Everything here is deterministic given its inputs: label placement is a greedy
pass over a caller-ordered list, and no layout draws on a random source that is
not seeded.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from make_figures import PALETTE, _text_width, esc  # noqa: E402

LABEL_FONT = 10.5
HALO = 3.0          # px of surface-coloured stroke behind label glyphs


# --- text -----------------------------------------------------------------
def halo_text(mode: str, x: float, y: float, text: str, anchor: str = "start",
              font: float = LABEL_FONT, weight: str = "400",
              fill: str | None = None) -> str:
    """A label that stays readable over edges and other marks.

    `paint-order="stroke"` paints the stroke first and the fill on top, so a
    surface-coloured stroke becomes a moat around each glyph rather than an
    outline over it. Without this, in-place labelling on a node-link diagram is
    not an option and the labels have to go in the margin.
    """
    p = PALETTE[mode]
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'font-size="{font:.1f}" font-weight="{weight}" '
            f'font-family="ui-sans-serif,system-ui,sans-serif" '
            f'fill="{fill or p["text_primary"]}" stroke="{p["surface"]}" '
            f'stroke-width="{HALO}" stroke-linejoin="round" '
            f'paint-order="stroke">{esc(text)}</text>')


def _box(x, y, w, h):
    return (x, y, x + w, y + h)


def _hits(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


# Candidate offsets around a node, in preference order: right, left, then the
# diagonals, then straight above and below. Right first because a label reads
# left-to-right away from its node.
_OFFSETS = [(1, 0), (-1, 0), (1, -1), (-1, -1), (1, 1), (-1, 1), (0, -1), (0, 1)]


def place_labels(nodes, width, height, font=LABEL_FONT, pad=2.0,
                 max_width=None):
    """Greedy in-place label positions. Returns `(node, x, y, anchor)` tuples.

    Nodes are taken in the order given — importance order, so the firms a
    reader is most likely to want are placed first and the ones that cannot fit
    are the least important. A node whose label fits nowhere is skipped rather
    than drawn overlapping: an unreadable label is worse than none, and the
    table view carries every name regardless.

    Deterministic by construction: no randomness, and the only input that
    decides the outcome is the caller's ordering.
    """
    taken = [(n["x"] - n["r"], n["y"] - n["r"], n["x"] + n["r"], n["y"] + n["r"])
             for n in nodes]
    out = []
    for n in nodes:
        label = n.get("label") or ""
        if not label:
            continue
        tw = _text_width(label, font)
        if max_width and tw > max_width:
            continue
        th = font * 1.1
        gap = n["r"] + 4.0
        for dx, dy in _OFFSETS:
            if dx > 0:
                x, anchor = n["x"] + gap, "start"
                bx = x
            elif dx < 0:
                x, anchor = n["x"] - gap, "end"
                bx = x - tw
            else:
                x, anchor = n["x"], "middle"
                bx = x - tw / 2
            y = n["y"] + dy * (gap + th * 0.4) + th * 0.34
            box = _box(bx - pad, y - th + pad, tw + 2 * pad, th)
            if box[0] < 0 or box[2] > width or box[1] < 0 or box[3] > height:
                continue
            if any(_hits(box, t) for t in taken):
                continue
            taken.append(box)
            out.append((n, x, y, anchor))
            break
    return out


# --- edges ----------------------------------------------------------------
def curved_edges(edges, mode, bow: float = 0.14, width_of=None, opacity_of=None,
                 colour_of=None) -> str:
    """Quadratic-bezier edges, batched by (colour, width, opacity).

    `edges` are `((x1, y1), (x2, y2), payload)`. The three `*_of` callables take
    the payload; the defaults give a recessive hairline.

    Batched into one `<path>` per style bucket rather than one element each, for
    the same reason `make_figures.draw_network` does it: per-element markup on a
    dense figure is megabytes of identical attributes and renders the same.

    The bow is a fixed fraction of each edge's own length, and always to the
    same side, so parallel edges between nearby nodes fan out instead of
    overprinting, and the picture does not depend on which way round the two
    endpoints happened to be stored.
    """
    p = PALETTE[mode]
    buckets: dict[tuple, list[str]] = {}
    for (x1, y1), (x2, y2), payload in edges:
        dx, dy = x2 - x1, y2 - y1
        # Control point offset perpendicular to the chord. Sorting the two ends
        # first makes the bow independent of storage order.
        if (x1, y1) > (x2, y2):
            cx = (x1 + x2) / 2 + dy * bow
            cy = (y1 + y2) / 2 - dx * bow
        else:
            cx = (x1 + x2) / 2 - dy * bow
            cy = (y1 + y2) / 2 + dx * bow
        colour = colour_of(payload) if colour_of else p["edge"]
        sw = width_of(payload) if width_of else 0.8
        op = opacity_of(payload) if opacity_of else 0.34
        key = (colour, f"{sw:.2f}", f"{op:.3f}")
        buckets.setdefault(key, []).append(
            f"M{x1:.1f} {y1:.1f}Q{cx:.1f} {cy:.1f} {x2:.1f} {y2:.1f}")
    out = ['<g fill="none" stroke-linecap="round">']
    for (colour, sw, op), segs in sorted(buckets.items()):
        out.append(f'<path d="{"".join(segs)}" stroke="{colour}" '
                   f'stroke-width="{sw}" stroke-opacity="{op}"/>')
    out.append("</g>")
    return "".join(out)


def arcs(pairs, mode, baseline: float, height: float, width_of=None,
         opacity_of=None, colour_of=None) -> str:
    """Semicircular arcs above a baseline: the arc-diagram edge.

    An arc diagram trades the two-dimensional layout for a readable node
    ordering. That is the right trade whenever the ordering is itself a
    variable — here, the territory a firm is filed under — because a force
    layout would place the nodes by connection and destroy it.
    """
    p = PALETTE[mode]
    buckets: dict[tuple, list[str]] = {}
    for x1, x2, payload in pairs:
        lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
        span = hi - lo
        rise = min(height, span * 0.55)
        colour = colour_of(payload) if colour_of else p["edge"]
        sw = width_of(payload) if width_of else 0.8
        op = opacity_of(payload) if opacity_of else 0.3
        key = (colour, f"{sw:.2f}", f"{op:.3f}")
        buckets.setdefault(key, []).append(
            f"M{lo:.1f} {baseline:.1f}"
            f"C{lo:.1f} {baseline - rise:.1f} {hi:.1f} {baseline - rise:.1f} "
            f"{hi:.1f} {baseline:.1f}")
    out = ['<g fill="none" stroke-linecap="round">']
    for (colour, sw, op), segs in sorted(buckets.items()):
        out.append(f'<path d="{"".join(segs)}" stroke="{colour}" '
                   f'stroke-width="{sw}" stroke-opacity="{op}"/>')
    out.append("</g>")
    return "".join(out)


# --- nodes ----------------------------------------------------------------
def circles(nodes, mode, ring: float = 1.8) -> str:
    """Node marks, each with a surface ring so overlaps stay legible."""
    p = PALETTE[mode]
    out = ["<g>"]
    for n in nodes:
        out.append(
            f'<circle class="nd" data-id="{esc(n["id"])}" cx="{n["x"]:.1f}" '
            f'cy="{n["y"]:.1f}" r="{n["r"]:.2f}" fill="{n["color"]}" '
            f'stroke="{p["surface"]}" stroke-width="{ring:g}"/>'
        )
    out.append("</g>")
    return "".join(out)


def hoverable(nodes, mode, ring: float = 1.8) -> str:
    """`circles`, but each node wrapped with its own tooltip."""
    p = PALETTE[mode]
    out = []
    for n in nodes:
        out.append(
            f'<g class="mk"><title>{esc(n.get("tip") or n.get("label") or n["id"])}</title>'
            f'<circle class="nd" data-id="{esc(n["id"])}" cx="{n["x"]:.1f}" '
            f'cy="{n["y"]:.1f}" r="{n["r"]:.2f}" fill="{n["color"]}" '
            f'stroke="{p["surface"]}" stroke-width="{ring:g}"/></g>'
        )
    return "".join(out)


def area_radius(value: float, hi: float, r_max: float, r_min: float = 2.6) -> float:
    """`r = r_max x sqrt(value / hi)`, so **area** is the value.

    The shared `make_figures.radius` takes its square root after rescaling the
    value to 0-1 across the drawn set, which is right for "bigger means more"
    and wrong for a caption that says area is a count: over a narrow range the
    rescaling turns a threefold difference into a twentyfold one.
    """
    if hi <= 0:
        return r_min
    return max(r_min, r_max * math.sqrt(max(value, 0.0) / hi))


# --- layouts --------------------------------------------------------------
def ring_layout(groups, cx, cy, radii, gap=0.0):
    """Concentric rings. `groups` is `[(radius_index, [node_id, ...]), ...]`.

    Each ring's members are laid out in the order given, so the caller controls
    the angular sort — sorting by community puts the communities in sectors and
    makes the rings comparable to each other.
    """
    pos = {}
    for idx, members in groups:
        r = radii[idx]
        n = max(len(members), 1)
        for i, node in enumerate(members):
            ang = 2 * math.pi * i / n - math.pi / 2 + gap
            pos[node] = (cx + r * math.cos(ang), cy + r * math.sin(ang))
    return pos


def column_layout(left_ids, right_ids, x_left, x_right, top, bottom):
    """Two evenly spaced columns: the two-mode drawing.

    A bipartite graph laid out by a force algorithm hides the one thing that
    makes it bipartite. Two columns state it, and every edge then runs left to
    right, so an edge crossing is a shared board rather than a layout accident.
    """
    pos = {}
    for ids, x in ((left_ids, x_left), (right_ids, x_right)):
        n = max(len(ids), 1)
        step = (bottom - top) / n
        for i, node in enumerate(ids):
            pos[node] = (x, top + step * (i + 0.5))
    return pos


def line_layout(ordered, x0, x1, y):
    """Nodes evenly spaced along a horizontal baseline, in the order given."""
    n = max(len(ordered), 1)
    step = (x1 - x0) / n
    return {node: (x0 + step * (i + 0.5), y) for i, node in enumerate(ordered)}
