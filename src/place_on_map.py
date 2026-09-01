"""Stage 20 - put the whole interlock network on the world map, or say why not.

    python3 src/place_on_map.py

    data/processed/company_map_positions.csv   one row per firm in the graph
    data/processed/territory_anchors.csv       the territory anchor points
    data/processed/map_tie_geography.csv       ties classified by geography
    data/processed/map_geography_baseline.csv  the denominators, one row

Figure 7 (stage 10) already puts the network on the map, but it maps **cities**:
it collapses each city to one node, so 762 Paris firms are one dot, and the
ties *inside* a city cannot be drawn at all. This stage places the firm
instead of the city, which is what makes a firm-level map possible — and to do
that it has to answer, for every one of the 5,989 firms in the interlock graph,
"where was it?"

For a third of them the honest answer is "the source does not say". So the
placement is a **ladder with three rungs**, and every row records which rung it
landed on, because the rungs do not mean the same thing:

1. **`city`** — an address. `geocode.py` (stage 6c) recovered a city from the
   firm's listed place or observed head office. 2,014 firms. Position is a
   fact about the firm.
2. **`territory`** — a filing category. The firm has no address but the
   catalogue files it under exactly **one** country, so it is placed at that
   territory's anchor point. Position is a fact about the *catalogue*, and
   several hundred firms filed under a colony were in truth run from Paris.
3. **`unplaced`** — no address and no single country. Three kinds: the firm has
   no country at all (1,650 firms, most of them filed only under the
   transversal *Empire* rubric); it is filed under several countries at once
   (420 firms), which is a real fact about the firm and not a gap, since a bank
   operating in nine territories has no point location; or its single country
   has no city in the gazetteer (9 firms — Macedonia, Russia, the Antarctic
   territories). Each row records which, in `reason`.

**Multi-country firms are deliberately not placed.** `companies.csv` stores
`countries` as a sorted list, so taking the first element would place a firm
filed under nine territories at whichever one sorts first alphabetically. That
is a coin flip dressed as a coordinate, and the firms it would misplace are
the largest and most interlocked in the corpus.

Territory anchors are the unweighted mean of that territory's cities in
`data/reference/places_geo.csv` — a label anchor, not a centroid of anything
real. The two federations (AOF, AEF) are the mean over their member
territories, listed in `FEDERATIONS` below.
"""

from __future__ import annotations

import csv
import math
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sectors as S  # noqa: E402
from build_network import read_csv, write_csv  # noqa: E402
from make_figures import build_interlock_graph, territory_of  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
GAZ = os.path.join(ROOT, "data", "reference", "places_geo.csv")

EARTH_KM = 6371.0

# The catalogue's country strings, folded onto the gazetteer's territory names.
# These are spelling and parenthetical variants of one place, not judgements:
# the left side is what `companies.csv` carries, the right what the gazetteer
# calls it.
TERRITORY_FOLD = {
    "Afrique occidentale francaise": "Afrique occidentale française",
    "Afrique equatoriale francaise": "Afrique équatoriale française",
    "Algerie": "Algérie",
    "Nouvelle-Calédonie (Mélanésie)": "Nouvelle-Calédonie",
    "Nouvelles-Hébrides (Mélanésie)": "Nouvelles-Hébrides",
    "Congo-Brazzaville ou Moyen-Congo": "Congo-Brazzaville",
    "Java et Sumatra (Indes néerlandaises)": "Java et Sumatra",
    "Oubangui-Chari (Centrafrique)": "Oubangui-Chari",
    "Inde (Comptoirs français de l’)": "Inde française",
    "Soudan français (Mali, Haute-Volta — ou Burkina-Fasso — et Niger)":
        "Soudan français",
    "Tahiti (Polynésie)": "Tahiti (Polynésie)",
}

# The two federations are administrative units, not places, and the gazetteer
# has no city for either. Their anchor is the mean over the member territories
# the corpus actually names.
FEDERATIONS = {
    "Afrique occidentale française": [
        "Sénégal", "Soudan français", "Côte d'Ivoire", "Dahomey (Bénin)",
        "Guinée Conakry", "Mauritanie",
    ],
    "Afrique équatoriale française": [
        "Gabon", "Congo-Brazzaville", "Oubangui-Chari", "Tchad",
    ],
}

TIE_CLASSES = ["colony only", "metropole-colony", "metropole only",
               "with foreign", "unplaced"]


def haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def territory_anchors() -> dict[str, dict]:
    """One anchor point per territory: the mean of its gazetteer cities."""
    cities: dict[str, list[dict]] = defaultdict(list)
    for r in read_csv(GAZ):
        cities[r["territory"]].append(r)

    def mean_of(members, kind):
        rows = [r for m in members for r in cities.get(m, [])]
        if not rows:
            return None
        return {
            "lat": round(sum(float(r["lat"]) for r in rows) / len(rows), 3),
            "lon": round(sum(float(r["lon"]) for r in rows) / len(rows), 3),
            "group": Counter(r["group"] for r in rows).most_common(1)[0][0],
            "n_cities": len(rows), "source": kind,
        }

    out = {}
    for terr in cities:
        out[terr] = mean_of([terr], "gazetteer mean")
    for fed, members in FEDERATIONS.items():
        anchor = mean_of(members, "federation mean")
        if anchor:
            anchor["members"] = "; ".join(members)
            out[fed] = anchor
    for terr, a in out.items():
        a.setdefault("members", "")
        a["territory"] = terr
    return out


def countries_of(rec: dict) -> list[str]:
    return [c for c in (rec.get("countries") or "").split("; ") if c.strip()]


def place(G, firms, places, anchors, sec_of) -> list[dict]:
    """The placement ladder, one row per firm in the interlock graph."""
    rows = []
    for cid in G.nodes():
        rec = firms.get(cid, {})
        row = {
            "company_id": cid, "name": rec.get("name", cid),
            "placement_level": "unplaced", "anchor": "", "anchor_territory": "",
            "group": "", "lat": "", "lon": "", "reason": "",
            "n_countries_listed": len(countries_of(rec)),
            "filed_territory": territory_of(rec),
            "sector_group": sec_of.get(cid, ""),
            "degree": G.degree(cid),
            "weighted_degree": sum(d.get("weight", 1)
                                   for _, _, d in G.edges(cid, data=True)),
        }
        p = places.get(cid)
        if p and p["city"]:
            row.update(placement_level="city", anchor=p["city"],
                       anchor_territory=p["city_territory"], group=p["group"],
                       lat=p["lat"], lon=p["lon"],
                       reason=p.get("source_field", ""))
            rows.append(row)
            continue
        cs = countries_of(rec)
        if len(cs) == 1:
            terr = TERRITORY_FOLD.get(cs[0], cs[0])
            a = anchors.get(terr)
            if a:
                row.update(placement_level="territory", anchor=terr,
                           anchor_territory=terr, group=a["group"],
                           lat=f"{a['lat']}", lon=f"{a['lon']}",
                           reason="single filing country")
            else:
                row["reason"] = f"country not in gazetteer: {terr}"
        elif not cs:
            row["reason"] = "no country listed"
        else:
            row["reason"] = f"filed under {len(cs)} countries"
        rows.append(row)
    return rows


def tie_class(a: dict, b: dict) -> str:
    ga, gb = a["group"], b["group"]
    if "foreign" in (ga, gb):
        return "with foreign"
    if ga == gb == "metropole":
        return "metropole only"
    if ga == gb == "empire":
        return "colony only"
    return "metropole-colony"


def classify_ties(G, pos: dict[str, dict]) -> tuple[list[dict], dict]:
    counts: Counter = Counter()
    weights: Counter = Counter()
    same_anchor: Counter = Counter()
    same_terr: Counter = Counter()
    lengths: list[float] = []
    for a, b, d in G.edges(data=True):
        w = d.get("weight", 1)
        pa, pb = pos.get(a), pos.get(b)
        if not pa or not pb:
            counts["unplaced"] += 1
            weights["unplaced"] += w
            continue
        k = tie_class(pa, pb)
        counts[k] += 1
        weights[k] += w
        if pa["anchor"] == pb["anchor"]:
            same_anchor[k] += 1
        else:
            lengths.append(haversine(float(pa["lat"]), float(pa["lon"]),
                                     float(pb["lat"]), float(pb["lon"])))
        if pa["anchor_territory"] == pb["anchor_territory"]:
            same_terr[k] += 1

    drawable = sum(v for k, v in counts.items() if k != "unplaced")
    rows = []
    for k in TIE_CLASSES:
        rows.append({
            "tie_class": k, "n_edges": counts[k], "n_interlocks": weights[k],
            "share_of_drawable": ("" if k == "unplaced"
                                  else f"{counts[k] / max(drawable, 1):.4f}"),
            "n_same_anchor": same_anchor[k], "n_same_territory": same_terr[k],
        })
    lengths.sort()
    stats = {
        "n_drawable": drawable,
        "n_same_anchor": sum(same_anchor.values()),
        "median_tie_km": round(lengths[len(lengths) // 2], 1) if lengths else "",
        "mean_tie_km": round(sum(lengths) / len(lengths), 1) if lengths else "",
    }
    return rows, stats


def main() -> None:
    firms = {r["company_id"]: r for r in read_csv(os.path.join(PROC, "companies.csv"))}
    ppath = os.path.join(PROC, "company_places.csv")
    if not os.path.exists(ppath):
        raise SystemExit("run: python3 src/geocode.py")
    places = {r["company_id"]: r for r in read_csv(ppath)}
    mapping = S.load_map()
    sec_of = {cid: S.sector_of(dict(r, company_id=cid), mapping)[0]
              for cid, r in firms.items()}

    G = build_interlock_graph(1)
    anchors = territory_anchors()
    rows = place(G, firms, places, anchors, sec_of)
    pos = {r["company_id"]: r for r in rows if r["lat"]}

    ties, stats = classify_ties(G, pos)

    write_csv(os.path.join(PROC, "company_map_positions.csv"), rows,
              ["company_id", "name", "placement_level", "anchor",
               "anchor_territory", "group", "lat", "lon", "filed_territory",
               "n_countries_listed", "sector_group", "degree",
               "weighted_degree", "reason"])
    write_csv(os.path.join(PROC, "territory_anchors.csv"),
              sorted(anchors.values(), key=lambda a: a["territory"]),
              ["territory", "lat", "lon", "group", "n_cities", "source",
               "members"])
    write_csv(os.path.join(PROC, "map_tie_geography.csv"), ties,
              ["tie_class", "n_edges", "n_interlocks", "share_of_drawable",
               "n_same_anchor", "n_same_territory"])

    lvl = Counter(r["placement_level"] for r in rows)
    paris = {r["company_id"] for r in rows if r["anchor"] == "Paris"}
    # Kept apart on purpose. A Paris tie whose other end is unplaced is not a
    # drawable tie, so counting it in the numerator and dividing by the
    # drawable total would overstate Paris's reach by twenty points.
    p_within = p_cross = p_unplaced = 0
    for a, b in G.edges():
        na, nb = a in paris, b in paris
        if na and nb:
            p_within += 1
        elif na or nb:
            if (a in pos) and (b in pos):
                p_cross += 1
            else:
                p_unplaced += 1
    n_anchors = len({r["anchor"] for r in rows if r["anchor"]})
    base = {
        "n_graph_firms": G.number_of_nodes(), "n_edges": G.number_of_edges(),
        "n_placed_city": lvl["city"], "n_placed_territory": lvl["territory"],
        "n_unplaced": lvl["unplaced"], "n_anchors": n_anchors,
        "n_drawable_edges": stats["n_drawable"],
        "n_same_anchor_edges": stats["n_same_anchor"],
        "median_tie_km": stats["median_tie_km"],
        "mean_tie_km": stats["mean_tie_km"],
        "paris_firms": len(paris), "paris_cross_edges": p_cross,
        "paris_within_edges": p_within, "paris_edges_to_unplaced": p_unplaced,
    }
    write_csv(os.path.join(PROC, "map_geography_baseline.csv"), [base],
              list(base))

    placed = lvl["city"] + lvl["territory"]
    print(f"\nplaced {placed:,}/{G.number_of_nodes():,} firms "
          f"({100 * placed / G.number_of_nodes():.1f}%) at {n_anchors} anchors: "
          f"{lvl['city']:,} by address, {lvl['territory']:,} by filing country; "
          f"{lvl['unplaced']:,} unplaced", file=sys.stderr)
    print(f"drawable ties {stats['n_drawable']:,}/{G.number_of_edges():,} "
          f"({100 * stats['n_drawable'] / G.number_of_edges():.1f}%), of which "
          f"{stats['n_same_anchor']:,} sit inside one anchor; median tie "
          f"{stats['median_tie_km']:,} km", file=sys.stderr)
    print(f"Paris: {len(paris):,} firms, {p_cross:,} drawable ties out, "
          f"{p_within:,} within, {p_unplaced:,} to unplaced firms — "
          f"{100 * (p_cross + p_within) / max(stats['n_drawable'], 1):.1f}% "
          f"of drawable ties touch Paris", file=sys.stderr)


if __name__ == "__main__":
    main()
