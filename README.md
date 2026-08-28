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

## What is in it

| | |
|---|---|
| Source documents catalogued | **5,920** (5,268 firms, 240 biographies, 412 thematic) |
| Documents with text extracted | **5,874 (99.2%)** — 46 are dead links on the site |
| Territories | **62** countries / 13 index-page regions (Maghreb, AOF, AEF, Indochina, Madagascar, Pacific, Antilles, Levant, French India) |
| Economic sectors | 108, as classified by the source |
| Person → company ties | **61,136** attributed observations of 79,343 parsed (77.1%) |
| Two-mode edge rows | **58,125**, 98.7% carrying a year |
| Distinct people | **24,458** |
| Companies | **8,493** (including firms known only from directory entries) |
| Company interlock edges | **39,523** pooled, 24,622 within period |
| Corporate directorships | 2,954 directed company → company edges |
| Period covered | 1830s–1970s, densest 1914–1944 |

`data/processed/network_stats.csv` holds these figures per period. The
versioned dataset is about 120 MB, most of it the two largest derived tables.

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

`person_id` and `company_id` match the top-level files, so bundles are
directly comparable. Ties partition across bundles; **nodes do not** — 21% of
people appear in more than one territory, so node counts must not be summed.
`territory_manifest.csv` reports each territory's counts and how much of its
elite is shared with others (0.29 for Morocco and Indochina, 0.72 for
Senegal).

### Positionality of individuals

`person_positionality.csv` codes each person `colonial` / `native`, with
`intermediate` for Maghrebi Jewish names and `local_non_french_elite` for
Ottoman and Egyptian ones, since neither fits the binary. The evidence is the
name plus the territory — onomastic inference, good for aggregate composition
and **not** for claims about named individuals.

The headline result is stark and is the point of the variable: of 24,458
people, **146 (0.6%) carry an indigenous name**. By territory, board members
with an indigenous name run at 1.0% in Morocco and Indochina, 0.4% in Algeria,
and **0.0% in French Equatorial Africa, Gabon, Congo-Brazzaville and New
Caledonia**. All 205 non-European codings are listed in
`positionality_review.csv` for hand-checking.

### Figures

`figures/interlock_network.html` is a self-contained page — open it in a
browser, no server and no build step — with three figures, hover tooltips, a
table view of the core firms and a dark mode. The same three are versioned as
standalone SVGs for papers.

| | |
|---|---|
| `fig1_core_interlocks.svg` | The core interlock network: 170 firms, 1,162 ties at two or more shared directors, coloured by territory and sized by weighted degree. |
| `fig2_by_period.svg` | The same network by period, five panels on one shared layout — 299 ties before 1914, 1,764 in 1914–1929, 116 after 1962. |
| `fig3_ego_indochine.svg` | The interlock neighbourhood of a single firm, the Banque de l'Indochine by default. |

Regenerate with `python3 src/make_figures.py`; `--top`, `--min-weight` and
`--ego` change the subset. **Read a figure as a map of the core, not of the
whole graph** — each is an explicit subset, and no figure is a basis for a
global claim about density or centralisation. METHODOLOGY §5d sets out the
three choices that could otherwise mislead.

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
  build_network.py     stage 4  ties         -> nodes, edges, projections, GraphML
  split_by_country.py  stage 5  dataset      -> per-territory bundles
  code_positionality.py stage 6 people       -> colonial / native coding
  make_figures.py      stage 7  network      -> figures (HTML + SVG)
  checks.py            188 assertions on the parsers and the built dataset
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
  interlock_network.html  three figures, interactive, self-contained
  fig*.svg                the same figures standalone, for papers
examples/
  explore.py           worked tour of the dataset
```

## Rebuilding from source

```bash
python3 src/crawl_catalogue.py                # ~1 min
python3 src/fetch_extract.py                  # ~1.5 h, ~21 GB transferred, resumable
python3 src/fetch_extract.py --retry-failed   # sweep transient network errors
python3 src/parse_ties.py                     # ~6 min
python3 src/build_network.py                  # ~3 min
python3 src/split_by_country.py               # ~2 min, per-territory bundles
python3 src/code_positionality.py             # ~1 min, positionality coding
python3 src/make_figures.py                   # ~1 min, figures/
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
  excluded from the network — **18,207 of 79,343 parsed ties, 22.9%** — instead
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
