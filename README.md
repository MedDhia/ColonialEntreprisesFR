# French Colonial Companies — a network dataset

A machine-readable dataset on French colonial companies, their directors and
the ties between them, built from
[entreprises-coloniales.fr](https://entreprises-coloniales.fr/).

It is designed for network analysis and social science research: the core
object is a **dated two-mode person × company affiliation network**, from which
interlocking-directorate and co-membership networks are projected. Every tie
carries the year it was observed and the source citation it came from, so the
network can be sliced by period rather than collapsed into one static graph.

> **Scope of the claim.** This is a dataset of *statements found in a
> documentary compilation*, not a census of colonial boards. Coverage is uneven
> by territory and period, and selection runs through both the compiler and the
> surviving press. Read [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) §6 before
> publishing results — especially for any measure sensitive to missing data.
>
> **Extraction coverage.** Of 5,863 documents carrying usable text — the
> 5,867 that extract cleanly, less four holding under 200 characters —
> **3,686 (63%) yield at least one tie** — up from 42% before the prose, annotation and
> biographical and roster parsers were added. The remaining 2,177 hold 26% of the
> extracted characters and contribute nothing: mostly genres no parser reads
> (honours lists, tariff schedules, balance-sheet-only extracts) plus real
> misses. §2b of the methodology quantifies what is left on the table. Absence
> of a firm from the network is not evidence that it had no board.
>
> **Six extraction genres, all merged, all separable.** Every genre is in the
> default network and every observation and two-mode edge carries
> `source_genre`, so filtering to the structured evidence never needs a
> rebuild (`--no-prose`, `--no-annotations`, `--no-biographical`,
> `--no-roster`, `--no-person-index` also exist).
>
> | Genre | Ties | Precision | What it reads |
> |---|---|---|---|
> | `dossier` | 63,820 | highest | board lists under a firm heading |
> | `person_index` | 15,632 | ~97% agreement with the source's own gloss | numbered annuaire indexes |
> | `prose` | 12,535 | ~90% | board changes reported in sentences |
> | `annotation` | 1,621 | ~94% | the compiler's inline notes |
> | `biographical` | 1,558 | ~93% | biographical dictionaries (**undated**) |
> | `roster` | 536 | 30/30 attribution, 23/25 resolution | the parliamentary directories (**dated by volume**) |
>
> Precision figures come from hand-checking random samples against source
> context. They locate an order of magnitude, not a second decimal.
> METHODOLOGY §4c–4k gives each audit and the failures it fixed. One further
> genre was built, measured at 8–9 of 15, and **deliberately not merged** — see
> METHODOLOGY §2b.
>
> **The network includes the Paris Bourse.** A large share of colonial firms
> were publicly quoted, so `Annuaire Desfossés 1956` is a colonial source; it
> contributes 15,632 ties and 1,889 firms, of which 11% also have dossier
> evidence. The rest are metropolitan and foreign companies that colonial
> directors also sat on — which is the point, but it means **this is no longer
> a purely colonial universe**. Every edge carries `source_genre`, so
> `source_genre == "dossier"` recovers the previous scope exactly.

## What is in it

| | |
|---|---|
| Source documents catalogued | **5,920** (5,268 firms, 240 biographies, 412 thematic) |
| Documents with text extracted | **5,874 (99.2%)** — 46 are dead links on the site |
| Territories | **62** countries / 13 index-page regions (Maghreb, AOF, AEF, Indochina, Madagascar, Pacific, Antilles, Levant, French India) |
| Economic sectors | 108, as classified by the source |
| Person → company ties | **102,871** — 63,820 from firm dossiers, 15,632 from the annuaire indexes, 12,535 from prose, 1,621 from annotations, 1,558 from biographies, 536 from the parliamentary rosters |
| Two-mode edge rows | **94,728**, 97.4% carrying a year |
| Distinct people | **34,518** |
| Companies | **10,373** (including firms known only from a directory or annuaire entry) |
| Company interlock edges | **79,072** pooled, 51,658 within period |
| Extraction genres | 6, all merged; `source_genre` on every observation and edge |
| Attribution | 86.9% of parsed ties resolve to a firm; `attribution` records how |
| Corporate directorships | 3,138 directed company → company edges |
| Politically connected firms | **2,243 of 6,454 with an observed board (34.8%)** — coded in `company_political.csv`, argued in `data/reference/political_connection_rules.md` |
| Period covered | 1830s–1970s, densest 1914–1944 |

`data/processed/network_stats.csv` holds these figures per period. The
versioned dataset is about 300 MB, most of it the person co-membership edge
list and the two-mode GraphML.

## Quick start

```bash
pip install -r requirements.txt
```

The derived datasets are versioned in `data/processed/`, so you can analyse
without re-running the pipeline.

```python
import pandas as pd

edges  = pd.read_csv("data/processed/edges_person_company.csv")
firms  = pd.read_csv("data/processed/companies.csv")
people = pd.read_csv("data/processed/persons_resolved.csv")

# Interwar board seats only
interwar = edges[(edges.is_board_seat == 1) & edges.period.eq("1914_1929")]

# Build the two-mode network and project it
import networkx as nx
B = nx.Graph()
B.add_nodes_from(interwar.person_id.unique(), bipartite=0)
B.add_nodes_from(interwar.company_id.unique(), bipartite=1)
B.add_edges_from(interwar[["person_id", "company_id"]].itertuples(index=False))
firm_net = nx.bipartite.weighted_projected_graph(B, interwar.company_id.unique())
```

Or load a ready-made graph:

```python
G = nx.read_graphml("data/graphs/company_interlock.graphml")   # or open in Gephi
```

`python3 examples/explore.py` prints a worked tour of the dataset: the
best-connected directors, the densest interlocks, sectoral and temporal
distributions, and a traced provenance chain from one tie back to its source
citation.

### Working with one territory

`data/by_country/<slug>/` and `data/by_region/<slug>/` hold self-contained
bundles — same columns as the top-level files, restricted to that territory,
with nodes and edges recomputed from its ties alone and a ready GraphML:

```python
mad = pd.read_csv("data/by_country/madagascar/edges_person_company.csv")
G   = nx.read_graphml("data/by_country/madagascar/company_interlock.graphml")
```

> **A bundle is defined by the source document, not by the firm.**
> `by_country/tunisie/` holds every firm with a tie read from a document filed
> on the site's Tunisia index page — **198 firms**. It is *not* "the Tunisian
> companies": **519 firms carry `Tunisie` in `companies.csv`'s `countries`
> field, and 402 of those are in the interlock graph.** The gap is firms whose
> Tunisian connection was recorded in a document filed elsewhere — a Paris
> holding company's dossier, an annuaire, a biography.
>
> The bundle rule is what makes tie counts sum across bundles, and it is the
> right unit for "what does the Tunisian record contain". For "which firms
> operated in Tunisia", filter the top-level file instead:
>
> ```python
> firms = pd.read_csv("data/processed/companies.csv")
> tunisian = firms[firms.countries.fillna("").str.contains("Tunisie")]
> ```

`person_id` and `company_id` match the top-level files, so bundles are
directly comparable. Ties partition across bundles; **nodes do not** — 21% of
people appear in more than one territory, so node counts must not be summed.
`territory_manifest.csv` reports each territory's counts and how much of its
elite is shared with others (0.29 for Morocco and Indochina, 0.72 for
Senegal).

### Who counts as one person

A person key is a normalised surname plus the first given initial, which is
too coarse on its own: Georges Hersent and Gilbert Hersent both key to
`hersent-g`, and unsplit they make every firm one sat on interlock with every
firm the other sat on. `build_network.py` resolves in both directions and
records every decision in `person_resolution.csv`.

- **Folds** a surname-only key into a unique surname+initial key — 1,916 of
  them — refusing when several candidates exist or the combined years imply a
  90-year career.
- **Splits** a key whose observations name forenames that cannot be one man —
  512 of them. Named observations move to `hersent-g-georges` and
  `hersent-g-gilbert`; the ones giving only `G.` stay on `hersent-g`, meaning
  *an unidentified G. Hersent*, and are handed to neither.

Together with the forename recovery below, this removed **2,940 interlock
edges that never existed**, with no observation lost — every tie is still
present, merely attributed to a narrower node. (The split alone accounts for
more than that; recovering forenames also collapsed junk keys back into real
people, which adds some edges back.) It is deliberately conservative — two forenames separate
only when both are independently attested and neither is a near-variant of the
other — so *Anathase*/*Athanase* Roudy and *Démétrius*/*Dimitri* Zafiropulo
stay merged, each being one man under two spellings. Check `given_variants` on
any high-degree node before trusting it.

### Positionality of individuals

`person_positionality.csv` codes each person `colonial` / `native`, with
`intermediate` for Maghrebi Jewish names and `local_non_french_elite` for
Ottoman and Egyptian ones, since neither fits the binary. The evidence is the
name plus the territory — onomastic inference, good for aggregate composition
and **not** for claims about named individuals.

The headline result is stark and is the point of the variable: of 34,447
people, **219 (0.6%) carry an indigenous name**. By territory, board members
with an indigenous name run at 1.0% in Morocco and Indochina, 0.4% in Algeria,
and **0.0% in French Equatorial Africa, Gabon, Congo-Brazzaville and New
Caledonia**. All 304 non-European codings are listed in
`positionality_review.csv` for hand-checking.

### Figures

Self-contained pages — open any of them in a browser, no server and no build
step — with hover tooltips, table views and a dark mode. Every figure is also
versioned as a standalone SVG for papers.

**`figures/descriptive.html`** — ten figures on what the data *is*, before any
network measure. Every other figure in this repository is a network; these are
the distributions and compositions a reader needs first, and each carries its
numbers in a table view beneath it.

| | |
|---|---|
| `fig8_ties_by_year.svg` | Dated observations per year, stacked by source genre. **1956 alone holds 19% of them** — one annuaire, read end to end. The spike is the shape of the source, not of the history. |
| `fig9_genre_by_period.svg` | Genre composition within each period. The person index falls entirely inside 1945–1962, so comparing periods without holding `source_genre` constant compares two ways of reading the archive. |
| `fig10_seats_per_person.svg` | Board seats per person, log scale. 16,784 people hold exactly one; the best-connected 1% hold 12%. |
| `fig11_board_size.svg` | Directors observed per firm-year. The mass sits at 3–12; the tail past 30 marks notices where several firms were run together. |
| `fig12_ties_by_territory.svg` | Ties per territory. Four territories hold most of them — absence elsewhere is a fact about the collection. |
| `fig13_ties_by_sector.svg` | Ties per sector, with the catalogue's "Documents généraux" filing heading excluded rather than shown as the largest industry. |
| `fig14_roles.svg` | Role composition. `administrateur` is also the default when a list qualifies nobody, so it pools qualified and unqualified seats. |
| `fig15_positionality.svg` | Indigenous share by territory, for those with 60+ recorded members. 21 sit at 0.0%. |
| `fig16_brokers_vs_hubs.svg` | The firms whose betweenness rank most exceeds their degree rank. A broker is not a hub. |
| `fig17_interlock_weight.svg` | Shared directors per interlock edge. **84% rest on a single person**, so one entity-resolution error removes the edge. |

**`figures/structure.html`** — ten figures on the *shape* of the graph, for a
reader about to compute something on it. Eight are measurements and two are
drawings, which is the split the questions ask for: "is this one lump or
several" is a number, and a hairball is not an answer to it. Every scalar these
quote is also in [`data/processed/network_measures.csv`](data/processed/network_measures.csv),
so none of them has to be read off an SVG.

| | |
|---|---|
| `fig18_degree_distribution.svg` | Degree CCDF on log–log axes, full graph against weight ≥ 2. Maximum degree falls from **499 to 157** once two shared directors are required. Both curves bend downward: the tail is shorter than a power law's, so **this network is not "scale-free"** and a fitted exponent would describe the source. |
| `fig19_kcore_profile.svg` | Firms per k-core shell. The profile should decay smoothly and does not: the shells at **k = 46 and k = 71 are complete graphs**, which no real board produces. The 24 empty levels below k = 71 are real — the deep core stands off from the rest. |
| `fig20_community_backbone.svg` | The 14 largest Louvain communities as nodes, sized by firm count, linked by shared directors. Modularity **0.48** — a real partition in which no block stands apart. |
| `fig21_giant_vs_threshold.svg` | Giant component against the weight threshold. **98.5% at one shared director, 47.4% at two.** The "connected" network is held together by single-name edges; any component or distance result has to state its threshold. |
| `fig22_path_lengths.svg` | Shortest-path distribution in the giant component, from 200 seeded sources. Mean **3.23**, longest observed 9 — but read it against fig21: this smallness is the one-shared-director graph's. |
| `fig23_community_territory.svg` | Territorial composition of the twelve largest communities. **None is territorially pure**; the most homogeneous tops out at 70%. Interlock clusters follow financial groups, not colonial borders. |
| `fig24_cross_territory.svg` | Interlocks joining two different territories: **67.5% of all edges**, falling from 73.8% pre-1914 to 46.4% post-1962. The source mix changes over the same span, so the trend is real in the data without being established as historical. |
| `fig25_person_reach.svg` | Seats held by the 30 people present in eight territories or more. Three of the identifiers shown are extraction residue rather than people, and are named as such rather than filtered out. |
| `fig26_innermost_core.svg` | The 72-firm deepest core, as observed and with one director's edges removed. **`homberg-o` sits on all 72 boards and generates all 2,556 of its edges by himself**; 532 survive without him and the core falls from k = 71 to k = 13. |
| `fig27_period_structure.svg` | Firms, edges, mean degree and giant-component share per period — four panels, four scales, because the units differ and a shared axis would make the comparison false. |

**`figures/nodes.html`** — the network at the scale of the individual firm.
Every other network figure here is drawn at the scale of the whole, where a
node is a dot and the fourteen labels that fit live in the margin. These six
are small enough to name every firm and follow every edge.

| | |
|---|---|
| `fig28_backbone.svg` | The 54 busiest firms of the graph at three or more shared directors, every one labelled. Cross-territory ties drawn darker and heavier — **129 of the 178**. |
| `fig29_core_rings.svg` | Every firm at k-core ≥ 25 on a ring for its core number, angle by community. Radius is a measured quantity, not a force-layout impression. |
| `fig30_arc_territory.svg` | The 56 busiest firms ranged by territory along an axis, ties as arcs. **231 of 314 arcs (74%) cross a border** — figure 24 seen firm by firm. |
| `fig31_shared_boards.svg` | The two-mode graph everything else is projected *from*: 14 directors, the 32 firms at least three of them sit on. Both columns ordered to minimise crossings. |
| `fig32_neighbourhoods.svg` | Six firms' neighbourhoods as small multiples, each cut to 15 ties so every node stays nameable. |
| `fig33_backbone_by_place.svg` | Figure 28's firms at figure 28's coordinates, recoloured by head office. **53% of the backbone firms with a recoverable address were run from metropolitan France.** |

**`figures/legislature.html`** — the parliamentary elite and the colonial
boards. The compiler assembled five directories to establish that
parliamentarians sat on these boards; these six figures ask which *continuity*
the record actually attests — a career's, a presence's, or a firm's access.
**1,448 deputies and senators are named in the corpus; 574 sat on a colonial
board; 111 sat in both chambers.**

| | |
|---|---|
| `fig34_mandate_terms.svg` | Terms of office as spans, one row per parliamentarian-director whose term is dated, ordered by first year. Surname-only keys and spans over 55 years are dropped: those are namesakes merged into one man. |
| `fig35_roster_presence.svg` | The five directories as a presence grid. **Carryover runs 0.471 → 0.794 → 0.568 across 1930–1936 and then 0.009 into 1954** — two of 232 men cross that gap. |
| `fig36_legislator_interlock.svg` | The 42 most connected parliamentarians by boards shared, ring ordered by chamber so a cross-chamber tie crosses the middle. Paul Doumer, Albert Lebrun, François de Wendel, Edmond Giscard d'Estaing. |
| `fig37_parliamentary_boards.svg` | The boards that carried the most parliamentarians. Continuous access and rapid succession are not separated here — fig 35 shows why that matters. |
| `fig38_seat_territory.svg` | Constituency against company territory. The Seine dominates because that is where boards met; Alger, Oran and Cochinchina read differently. |
| `fig39_direct_or_proxy.svg` | Held personally against held through a relative — the compiler's own distinction, kept out of the main network. **31 of 587 roster ties are proxy holdings.** |

**`figures/political.html`** — companies coded by political connection. A firm
is connected when one of its directors is attested holding an office of state:
deputy, senator, minister, governor-general, résident, colonial administrator,
prefect, or a named relative of a parliamentarian. **2,243 of 6,454 firms with
an observed board (34.8%) are connected.** The definition, the tier ordering,
the offices rejected and the four things the coding cannot do are in
[`data/reference/political_connection_rules.md`](data/reference/political_connection_rules.md)
— read it before citing the number.

| | |
|---|---|
| `fig40_connection_tiers.svg` | The five tiers. Tier 0 (4,211 firms) is not plotted — it flattened the four bars that carry the finding — and its size is in the note and the table. |
| `fig41_sitting_or_former.svg` | Sitting against former, by tier, never summed. **In the executive tier 473 of 884 firms carry a *former* office-holder; in the legislature tier only 35 of 713.** Ministers and governors join boards after leaving office; deputies sit while serving. |
| `fig42_connection_by_territory.svg` | Share connected by territory, with the denominator printed beside every bar. Tracks documentary coverage first — not a rate. |
| `fig43_connected_boards.svg` | The most connected boards: connected directors against total board membership observed. Banque de l'Indochine, Banque industrielle de Chine, Messageries maritimes. |
| `fig44_concurrency.svg` | The honest denominator. Of 4,212 connected director–firm pairs, **688 can be tested for simultaneity and 326 overlap** — fewer than one in five is testable at all. |

**`figures/interlock_network.html`** — the core of the network.

| | |
|---|---|
| `fig1_core_interlocks.svg` | The core interlock network: 170 firms, 1,401 interlocks at two or more shared directors — the core of a graph of 3,550 firms. Coloured by territory, sized by weighted degree. |
| `fig2_by_period.svg` | The same network by period, five panels on one shared layout — 479 ties before 1914, 2,943 in 1914–1929, 152 after 1962. |
| `fig3_ego_indochine.svg` | The interlock neighbourhood of a single firm, the Banque de l'Indochine by default. |
| `fig6_core_betweenness.svg` | The same 170 firms and the same layout as figure 1, sized by **betweenness centrality** instead of shared directorships — so the difference between the two figures is the finding. |

**`figures/city_network.html`** — the empire on the map.

| | |
|---|---|
| `fig7_city_network.svg` | Firms placed at their **city**, not their colony, in true coordinates; an edge joins two cities when a director sat on a board in each. 111 cities, 2,009 firms. |

The finding is stark: **37% of the placeable firms in the interlock graph were
run from Paris** — more than the next eleven cities combined — and the heavy
lines radiate from Paris outward rather than running between colonies. Read it
with the three limits the figure states: only 33% of interlocked firms have a
recoverable address, a head office is not an operation (a Cochinchina
plantation run from Paris appears at Paris), and the 5,146 ties *within* a
single city cannot be drawn as edges and are in the table instead.

**`figures/territory_networks.html`** — the whole empire, and every territory.

| | |
|---|---|
| `fig4_empire_network.svg` | **Every** firm sharing a director: 5,959 firms, 78,530 interlocks, nothing subsetted. Colour is territory. |
| `fig5_territory_matrix.svg` | The empire as a network of territories — 54 × 54 cells, each the number of directors sitting on boards in both. |
| `by_country/<slug>.svg` | 42 figures, one per territory with an interlock, each that territory's complete graph — `algerie`, `tunisie`, `madagascar`, `indochine`, `senegal`, … |

Every figure is versioned four ways: `<name>.svg` and `<name>.png` beside it,
and the same pair again under `figures/en/` with the territory and sector
labels in English. The PNGs are 2× (retina-sharp on screen, fine printed a
page wide) and are what GitHub previews inline.

**Firm and person names are never translated.** *Banque de l'Indochine* is a
legal name, not a description; an English "Bank of Indochina" would be a name
that appears in no archive. What the English figures translate is the
classification vocabulary — territories, regions, sectors — which is
description, and for which *Morocco* and *French West Africa* are the standard
forms in English-language scholarship. The mapping for all 183 categories is
`data/reference/labels_en.csv`, joinable on any `country`, `region` or
`sector` column.

```bash
python3 src/make_figures.py             # figs 1-3, ~1 min
python3 src/make_territory_figures.py   # figs 4-5 and the 42, ~1 min
python3 src/render_png.py               # all as PNG, ~90 s
python3 src/make_figures.py --lang en           # the English set
python3 src/make_territory_figures.py --lang en
```

`--top`, `--min-weight` and `--ego` change what figures 1–3 draw;
`--level region` switches the territory figures to the 12 index-page regions;
`--scale 3` and `--only <stem>` control the PNG pass.

**Colour is capped at three territories**, so on figures 1 and 4 Algeria,
Tunisia, Madagascar and the rest fall into the recessive grey. That is a
constraint of the form — a node-link diagram can put any two colours side by
side, so the palette has to survive an all-pairs test — not a judgement about
those territories. Each has its own figure in `by_country/`, where it is the
whole subject.

**Figures 1–3 are maps of the core, not of the whole graph** — each is an
explicit subset, and none is a basis for a global claim about density or
centralisation. Figure 4 is the whole graph but too dense to read firm by
firm; it answers whether the empire's boards were one integrated elite or
separate territorial ones. METHODOLOGY §5d sets out the choices in both that
could otherwise mislead.

### Which edge file to use

Start from **`edges_person_company.csv`** — everything else is derived from it.
For anything temporal or causal use
**`edges_company_interlock_by_period.csv`**, not the pooled interlock file: the
pooled version links firms whose shared director sat on the two boards decades
apart.

## Repository layout

```
src/
  common.py            HTTP, slugs, catalogue-title grammar, reference lists
  names.py             French personal and corporate name parsing
  crawl_catalogue.py   stage 1  index pages  -> document catalogue
  fetch_extract.py     stage 2  PDFs         -> plain text
  parse_ties.py        stage 3  text         -> companies, people, dated ties
  parse_person_index.py stage 3b inverted indexes -> person -> company ties
  parse_prose.py       stage 3c prose      -> boards reported in running text
  resolve_annotations.py stage 3d notes    -> the compiler's inline affiliations
  parse_biographies.py stage 3e biographical dictionaries -> career affiliations
  build_network.py     stage 4  ties         -> nodes, edges, projections, GraphML
  split_by_country.py  stage 5  dataset      -> per-territory bundles
  code_positionality.py stage 6 people       -> colonial / native coding
  make_figures.py      stage 7  network      -> core figures (HTML + SVG)
  make_territory_figures.py
                       stage 8  network      -> empire and per-territory figures
  render_png.py        stage 9  figures      -> PNG, one network per file
  centrality.py        stage 6b betweenness -> company_centrality.csv
  geocode.py           stage 6c addresses   -> company_places.csv (city level)
  make_geo_figure.py   stage 10 places      -> the map figure
  make_descriptive_figures.py
                       stage 11 dataset     -> the ten descriptive figures
  make_network_figures.py
                       stage 12 graph       -> the ten structural figures
  draw.py              node-level drawing primitives (curved edges, halo labels)
  make_node_figures.py stage 13 graph       -> the six node-level figures
  labels.py            English labels for the French category vocabulary
  checks.py            1,362 assertions on the parsers and the built dataset
data/
  processed/           the dataset (versioned)
  by_country/          per-country bundles (54 territories)
  by_region/           per-region bundles (12 index-page groupings)
  reference/           place and forename lists used by the parsers
  graphs/              GraphML exports
  text/                extracted plain text (not versioned; reproducible)
docs/
  CODEBOOK.md          every file, every variable, every value list
  METHODOLOGY.md       construction, coding decisions, validity limitations
figures/
  interlock_network.html  figures 1-3, interactive, self-contained
  territory_networks.html figures 4-5 and all 42 territories
  city_network.html       figure 7, the empire on the map
  descriptive.html        figures 8-17, what the data is
  structure.html          figures 18-27, what shape the graph has
  nodes.html              figures 28-33, the network firm by firm
  fig*.svg, fig*.png      the same figures standalone, for papers
  by_country/             one SVG and one PNG per territory
  en/                     the same figures with English category labels
examples/
  explore.py           worked tour of the dataset
```

## Rebuilding from source

```bash
python3 src/crawl_catalogue.py                # ~1 min
python3 src/fetch_extract.py                  # ~1.5 h, ~21 GB transferred, resumable
python3 src/fetch_extract.py --retry-failed   # sweep transient network errors
python3 src/parse_ties.py                     # ~6 min
python3 src/parse_person_index.py             # ~1 min, person-indexed annuaires
python3 src/parse_prose.py                    # ~4 min, prose-reported boards
python3 src/resolve_annotations.py            # after stage 4; inline notes
python3 src/parse_biographies.py              # after stage 4; Qui êtes-vous ?, etc.
python3 src/parse_rosters.py                  # after stage 4; the parliamentary directories
python3 src/build_network.py                  # ~3 min
python3 src/split_by_country.py               # ~2 min, per-territory bundles
python3 src/code_positionality.py             # ~1 min, positionality coding
python3 src/centrality.py                     # ~1 min, exact betweenness
python3 src/geocode.py                        # place firms at city level
python3 src/make_figures.py                   # ~1 min, core figures
python3 src/make_territory_figures.py         # ~1 min, empire + per-territory
python3 src/make_figures.py --lang en          # English label set
python3 src/make_territory_figures.py --lang en
python3 src/make_geo_figure.py                # the map
python3 src/make_geo_figure.py --lang en
python3 src/parse_mandates.py                 # ~4 min, deputies and senators
python3 src/parse_offices.py                  # ~4 min, offices of state
python3 src/make_legislative_layer.py         # the legislative join
python3 src/code_political_connections.py     # company-level connection coding
python3 src/make_political_figures.py         # figs 40-44
python3 src/make_political_figures.py --lang en
python3 src/make_legislative_figures.py       # figs 34-39
python3 src/make_legislative_figures.py --lang en
python3 src/render_png.py                     # ~90 s, PNG of every figure
python3 src/checks.py                         # must pass
```

Stage 2 is resumable and streams each PDF through memory, so the ~21 GB of
source material never lands on disk. It reaches 5,874 of 5,920 documents;
the 46 misses are dead links on the site (HTTP 404), recorded as
`fetch_error` in `text_extraction.csv` rather than dropped. Stages 3 and 4
are pure functions of the text cache — that is where to iterate when changing
coding rules.

**PyMuPDF is a hard requirement.** The source PDFs embed subsetted Type1 fonts
with MacRoman encodings; `pypdf` and `pdfminer` decode them into a
substitution cipher *silently*, returning well-formed nonsense
(`«uëliéHlïHYeHjênviïr` for "Publié le 19 janvier"). A pipeline built on
either would yield a large, plausible, fictitious dataset. `checks.py` guards
against this — run it after any change to extraction.

## Design commitments

The parsers make a lot of judgement calls on messy historical prose. Three
rules govern them, and they are worth knowing before you trust a number:

- **Every row keeps its raw string and its source.** `member_raw`,
  `title_raw`, `source_ref` and `doc_id` are on the observation tables so any
  coding decision can be audited or redone.
- **Entity resolution is minimal and reversible.** `person_id` folds a
  surname-only key into a surname-plus-initial key only when that key is
  unique for the surname *and* the years fit one career. Every decision,
  including every refusal, is in `person_resolution.csv`. Company name
  variants that keying cannot merge are listed in
  `company_duplicate_candidates.csv` for review rather than merged on a
  similarity threshold.
- **A coverage gap beats a fabricated attribution.** Where the parser cannot
  determine which firm a board belongs to, the tie is left unattributed and
  excluded from the network — **10,102 of 77,080 parsed ties, 13.1%** — instead
  of being credited to the previous firm in the document. They stay in
  `affiliations.csv` with an empty `company_key`, so the gap is inspectable
  rather than hidden.

Known limitations, in the order they are likely to bite: same-surname
same-initial contemporaries are merged into one node; unreviewed duplicate
company nodes split a firm's degree; directory years are snapshots, not
tenures; capital figures are unnormalised text across several currencies and
devaluations. All are set out in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Attribution

The underlying documents are the work of the compiler of
**entreprises-coloniales.fr**, who transcribed them from the colonial and
financial press. Any use of this dataset should cite that site as the source
of the material; this repository provides only the extraction pipeline and the
derived structure. The PDFs themselves are not redistributed here — the
pipeline fetches them from the site.

Please also check the site's own terms before redistributing extracted text.

## Licence

Pipeline code: see [`LICENSE`](LICENSE). The derived data is subject to the
rights in the underlying source material described above.
