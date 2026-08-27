# Methodology

How this dataset was built, what the constructed variables mean, and where it
will mislead you. Read §6 before publishing anything from it.

---

## 1. The source

[entreprises-coloniales.fr](https://entreprises-coloniales.fr/) is a
documentary collection on French colonial companies, compiled and maintained
by a single editor. It consists of 13 hand-written territory index pages
linking to 5,920 PDF dossiers. A typical dossier compiles transcribed
extracts about one firm — press reports, statutes, general-meeting notices,
annual-directory entries — each with its publication and date. A minority of
dossiers are whole annual directories covering hundreds of firms at once.

Two properties make it usable as a dataset. First, the extracts are
**transcribed rather than scanned**: every PDF carries a text layer keyed by
the compiler, so there is no OCR error. Second, they are **cited**: nearly
every extract names its publication and date, so a board list can be given a
year rather than floating free.

Two properties limit it. It is a **secondary compilation**, so its selection
of firms and extracts reflects the compiler's interests and the survival of
the underlying press. And its coverage is **uneven by design** — Indochina,
Algeria and Morocco have far more dossiers than the Pacific or the Antilles.
Neither is a defect of the site; both are constraints on inference from it.

`robots.txt` permits crawling and specifies no delay. The crawler identifies
itself, retries with exponential backoff, and fetches each PDF once.

## 2. Pipeline

Four stages, each resumable, each writing its own outputs:

1. **`crawl_catalogue.py`** — the 13 index pages → `documents.csv`,
   `document_listings.csv`.
2. **`fetch_extract.py`** — each PDF → gzipped plain text in `data/text/`,
   plus `text_extraction.csv`.
3. **`parse_ties.py`** — text → `affiliations.csv`, `org_affiliations.csv`,
   `company_attributes.csv`, `doc_references.csv`.
4. **`build_network.py`** — observations → nodes, edges, projections, GraphML.
5. **`split_by_country.py`** — dataset → per-territory bundles (§5b).

`checks.py` validates the parsers and the built dataset (139 assertions).

### The extraction trap

The PDFs embed subsetted Type1 fonts with MacRoman encodings. `pypdf` and
`pdfminer` both decode these into a **monotonic substitution cipher** — and,
critically, they do so *silently*. "Publié le 19 janvier" is returned as
`«uëliéHlïHYeHjênviïr`, which is well-formed text of the right shape and
length. A pipeline built on either library would produce a large, plausible,
entirely fictitious dataset.

PyMuPDF resolves the font encodings correctly. It is therefore a hard
requirement, not a preference, and `checks.py` asserts that ordinary French
function words survive extraction and that the cipher's signature (a literal
`H` where spaces belong) is absent. **Do not swap the extraction backend
without running that check.**

PDFs are streamed into memory and discarded after extraction; the ~21 GB of
source material never touches disk. Extracted text is ~10× smaller gzipped
and is not versioned, being fully reproducible.

## 3. Reading the catalogue titles

The index titles follow a consistent hand-keyed grammar:

```
<distinctive name> (<generic head>)(<acronym|dates>), <place> : <editorial gloss>
```

Company names are **inverted** so that lists alphabetise on the distinctive
word, with the generic head pushed into the first parenthesis: *Africaine de
Mines (Société)*. The parser un-inverts these into `name_normalised`.

The shape of the first parenthesis is also what separates a firm from a
biography, and it decides what the date range means:

| First parenthesis | `entry_type` | Date range is |
|---|---|---|
| generic head or article — `(Société)`, `(L')` | `company` | operating period |
| forename — `(Adolphe)`, `(Ch. et Louis d')` | `person` | life dates |

Getting this wrong in either direction is costly, so the test is explicit
rather than statistical. An earlier heuristic that simply looked for a
`(Surname)(dates)` shape classified 1,123 entries as people; most were firms
whose date parenthesis recorded when they operated. The current rule yields
240 biographies, 5,268 firms and 412 thematic documents.

Firms named after a person stay classified as firms — *Ferme de Gazan (Lucien
Deyme)* is a farm, not a man — but the personal name is recorded in
`principal_name` so the tie is not lost.

Two reference lists support this, both derived from the catalogue itself and
then reviewed by hand: `places.txt` (trailing place segments) and
`forenames.txt` (forenames occurring in first parentheses, extended with
common French forenames of the 1850–1950 cohorts). They are inputs, so
editing them changes the output.

The index markup also encodes structure that is easy to miss: nested
`ul.DL`/`ul.SDL` lists group a firm's successive corporate identities and its
subsidiaries under a link-less list item that names the group. That hierarchy
is reconstructed into `group_path` for 823 entries.

## 4. Constructing entities

This is where a network dataset from historical text is won or lost. Neither
people nor firms carry identifiers in the sources; both are named
inconsistently. The approach here is **conservative and reversible**: make the
minimum defensible identification, record every decision, and keep the raw
string on every row.

### People

Board lists mix registers within a single line:

```
MM. Georges Despret, présid. ; A. R. Fontaine (Distill. Indoch.), admin.-dél. ;
Dr H.-A. Van Nierop, baron Carton de Wiart, administrateurs
```

Names are split into honorific / given / surname by consuming leading
initials, then leading recognised forenames, with a positional fallback for
forenames not on the list. Handled registers: initials (`A. R. Fontaine`),
surname-first with parentheses (`PHILIPPAR (Edmond)`) and without
(`Chabert Pierre`), nobiliary and Dutch/German particles (`de Margerie`,
`Van Nierop`), and the sources' in-place expanded initials
(`P(aul) Delorme`).

Two refusals are deliberate. After an honorific, a name followed by a
particle is **not** split — `baron Carton de Wiart` keeps `Carton de Wiart`
as one surname, where the positional fallback would have made "Carton" a
forename. And an unrecognised first token followed by a particle is left
inside the surname, so `Carlos de Barros Soares Branco` becomes one surname
rather than a guess.

`person_key` = normalised surname + first given initial (`fontaine-a`).
`build_network.py` then applies **one** further fold: a surname-only key is
merged into a surname-plus-initial key when that key is unique for the
surname *and* the combined observation years fit within a 60-year career.
`Katz` folds into `katz-m`; it would not if an `E. Katz` also existed, nor if
the years implied a 90-year career. Refusals are recorded as
`unfolded_ambiguous` or `unfolded_year_span` in `person_resolution.csv`,
which is the complete audit trail.

**What this does not do.** Two contemporaries who share a surname and a first
initial are one node. Given the composition of this elite — Fontaine,
Hersent, Denis, Gradis and Homberg all appear as families operating across
several firms — that is a real and unquantified source of inflated degree.
The countermeasure available to you is `merged_keys`, `name_variants` and the
year span on every person node.

### Firms

`company_id` is derived from the name: accents, punctuation, legal forms and
stopwords are stripped, so *Compagnie des Chemins de fer du Maroc* and *Cie
des chemins de fer du Maroc* resolve together. An appended predecessor name
is removed first, so *Omnium nord-africain* and *Omnium nord-africain (Anct
Bonnaud et Cie)* also resolve together.

Names that differ in **content** do not merge — *abattoirs municipaux
industriels maroc* against *abattoirs municipaux maroc*, where one source
drops a word. Fuzzy matching would fix some of these and silently corrupt
others, so instead every plausible pair is written to
`company_duplicate_candidates.csv` for review. **An unreviewed duplicate
splits one firm's degree across two nodes**, which matters for centrality and
for component structure.

## 5. Dating and attributing ties

A document is split at **anchors** — points that fix a date, a source, or a
company. Text between one anchor and the next inherits that anchor's
attributes. Anchors are dated press citations, inline directory entries
(`AEC 1922-519 —`, `Annuaire Desfossés, 1945`), numbered directory entries,
capitalised *Annuaire industriel* headings, and the "local companies"
register. Board lists inside a segment are then found by explicit list
markers and parsed into person/role pairs.

Three failure modes were found by inspecting output rather than code, and each
one shaped the design:

**Prose read as lists.** A case-insensitive `conseil d'administration` trigger
matches ordinary narrative constantly — *"le conseil d'administration est
autorisé à émettre des obligations"* — and swallowing the following paragraph
turned sentence fragments into thousands of fictitious directors. Triggers are
now anchored on real list markers: a capitalised heading, a directory field
label, or a phrase that announces a list. Every candidate list must also pass
a shape test (an `MM.` marker, or a majority of short name-like
comma-separated fragments), and overlapping trigger matches are deduplicated
by span so one list is not counted once per matching pattern.

**Dates borrowed from history notes.** Treating any parenthesis containing a
comma and a four-digit year as a citation caught *"(Anciens Éts Salmon, fondés
en 1818)"*, then carried 1818 forward as the observation year for every board
that followed. The symptom was careers of 150 years. Citations now require an
actual date structure — an optional day, an optional French month name, then
the year at the end — and parentheses narrating a firm's origins are rejected
outright. Afterwards 47 of 13,000 people exceed a 60-year span, and the tie
distribution peaks in the interwar decades, as the underlying history implies.

**Attribution running past the end of a register.** Directories change format
part-way through. When one register went unrecognised, the last successfully
parsed firm stayed in scope and absorbed the boards of everything after it —
one firm was credited with 1,286 ties. Two changes: a directory entry now
*replaces* the company in scope even when its own name fails validation, and
an entry's scope is capped at 6,000 characters. Both convert a silent
misattribution into a visible coverage gap, which is why **~10% of parsed
person-ties carry no `company_key`** and are excluded from the network. That
gap is the price of not fabricating attributions, and it is recorded rather
than hidden.

Related filters: periodical titles (which sit inside citations) and
balance-sheet captions (which sit in tables next to boards) are rejected as
entities, or "Gazette du Palais" accumulates directorships. Corporate board
members are routed to `org_affiliations.csv` rather than parsed as people.
Years outside 1800–2025 are discarded wherever a date is parsed.

## 5b. Splitting by territory

`split_by_country.py` writes one self-contained bundle per territory at two
granularities (54 countries, 12 index-page regions). Two bugs had to be fixed
first, both of which would have made a country split actively misleading.

**Territory labels.** A page covering several territories marks only the
*first* with `h2.premierTitrePays`; every later one uses `h2.titrePays`. The
crawler collected the latter and then discarded it, so the country label never
advanced: all 189 Madagascar documents were filed under *Djibouti*, and all of
Guyane, Brazil, Chile and Peru under *Guadeloupe-Martinique* — 19 territories
across 5 pages. Splitting on that would have shipped a "Djibouti" bundle
consisting mostly of Madagascar.

**Multi-firm surveys as firms.** Some dossiers survey many companies at once,
and their own gloss says so: *"notices sur 26 sociétés d'Indochine"*, *"28
françaises, 17 anglaises. Notices."* Treated as single firms, they became
nodes that absorbed every board they listed, reaching 254 and 286 distinct
directors and outranking the Banque de l'Indochine (92) at the top of the
degree distribution. They are now classified as source documents on the
strength of that gloss, which matches exactly two catalogue entries. A
companion rule that suggests itself — treating `par <Author>` as a
bibliographic marker — was tested and **rejected**: in French addresses "par
X" means *via* X (*"Oued-Marsa, par Sidi-Rehane"*), so it matched 41 entries
of which most are genuine firms. A third candidate, treating a plural
"Sociétés …" name as a survey, was also rejected: of 151 such entries almost
all are real firms (*Entreprises Boussiron*, *Comptoirs d'Hippone*).

Three design decisions in the split itself:

- **Ties partition, nodes overlap.** Each tie carries one territory, so bundle
  tie counts sum to the dataset total. Firms and people appear in every bundle
  where observed (21% of people, 9% of firms in more than one), so node counts
  must not be summed. The overlap is reported per territory rather than hidden.
- **Person resolution is global.** The crosswalk is computed once over the
  whole dataset and then applied to each slice, so one individual keeps one
  `person_id` everywhere. Resolving within slices would have given the same
  person different ids in Morocco and Indochina — destroying precisely the
  transcolonial careers this dataset is built to expose.
- **`Empire (transversal)` is kept as its own bundle** and labelled as not a
  country, since it is the source's grouping for firms spanning several
  colonies and is one of the largest buckets.

The per-territory share of shared elite is a usable variable in its own right:
~0.29 in Morocco, Indochina and Madagascar against 0.72 in Senegal and 0.62 in
Côte d'Ivoire, which is a measurable difference in how far a territory's
boards were staffed by men also sitting elsewhere.

## 6. Validity — read this before using the data

**It is a sample of statements, not a census of boards.** A firm's absence
from a period means no transcribed extract in this collection reports its
board then. It does not mean the firm was inactive, and it certainly does not
mean the board was empty. Any measure sensitive to missing data — density,
centralisation, component structure — is a statement about the *collection*
unless you can defend the coverage assumption separately. Coverage is very
uneven across territories and years; `network_stats.csv` and
`parse_report.csv` are the places to look before assuming otherwise.

**Selection runs through the compiler and the press.** Firms enter because
someone wrote about them and the compiler chose to transcribe it. Large,
Paris-financed, scandal-prone and long-lived firms are over-represented
relative to small local ones. This is a plausible correlate of centrality, so
"important firms are central" is partly built into the sampling frame.

**Directory years are snapshots, not spells.** An annual directory reports the
board as of publication. The dataset records the observation year, not a
tenure. `first_year`/`last_year` on a collapsed edge bound the *observations*,
not the appointment and departure. Do not read them as spells without
additional evidence, and be careful with survival or duration models.

**Roles are as stated.** The sources rarely distinguish an executive chairman
from a non-executive one, and `président` covers both. `BOARD_ROLES` in
`build_network.py` implements the conventional definition (an interlock is a
shared board seat, so auditors and salaried managers are excluded); widen or
narrow it deliberately rather than by default.

**Pooled interlocks are anachronistic.** `edges_company_interlock.csv` pools
all years, so it links firms whose shared director sat on the two boards
decades apart. Use `edges_company_interlock_by_period.csv`, or build your own
windows from `edges_person_company.csv`, for anything temporal or causal.

**Capital figures are not comparable as given.** They are unnormalised text in
the source's currency and denomination, spanning the 1928 franc devaluation,
wartime inflation and post-1945 revaluations, plus colonial currencies
(piastre, CFA franc). Convert before comparing across years.

**Region is the document's, not the tie's.** A Paris financier on the board of
a Moroccan company is recorded with `region = Maroc`. Treat region as an
attribute of the firm's dossier, not of the person.

**Two relations are the compiler's, not the archive's.**
`edges_company_reference.csv` records where the compiler linked one dossier to
another. It is an informed relatedness signal and a good lead generator; it is
not observed corporate structure. `annotation` on a tie is likewise the
compiler's identification of a person's other affiliations — valuable, and
worth verifying against the ties table before citing.

**Names are not disambiguated against external biographical sources.** No
authority file (Léonore, Sycomore, BnF, Annuaire Desfossés indexes) was
consulted. Cross-checking the top few hundred people against Léonore would
materially improve the person nodes and is the highest-value extension.

## 7. Reproducing and extending

```bash
pip install -r requirements.txt
python3 src/crawl_catalogue.py                  # ~1 min
python3 src/fetch_extract.py                    # ~1.5 h, ~21 GB transferred, resumable
python3 src/fetch_extract.py --retry-failed     # sweep transient network errors
python3 src/parse_ties.py                       # ~6 min
python3 src/build_network.py                    # ~3 min
python3 src/checks.py                           # must pass
```

Extraction reaches 5,874 of 5,920 documents (99.2%): 5,867 with a text layer
and 7 that are image-only, recorded as `no_text_layer`. The remaining 46 are
dead links on the site, returning HTTP 404, and are recorded as `fetch_error`
in `text_extraction.csv` rather than dropped.

Stage 2 is resumable: rerunning skips documents already extracted. Stages 3
and 4 are pure functions of the text cache and can be rerun freely — the
place to iterate when changing coding rules.

To change a coding decision, the useful entry points are: `BOARD_ROLES` and
`PERIODS` in `build_network.py`; `TRIGGERS` and `ROLE_RULES` in
`parse_ties.py`; `MAX_CAREER_SPAN` for person folding; and the two reference
lists in `data/reference/`. Rerun `checks.py` after any of them.

Highest-value extensions, roughly in order: (1) reconcile people against
Léonore and other authority files; (2) review
`company_duplicate_candidates.csv` and ship an accepted-merge list; (3) parse
shareholder and capital-subscription lists, which are present in the text and
currently unused; (4) normalise capital into constant francs; (5) parse the
biographical dossiers, whose 240 documents contain career sequences this
pipeline does not touch.
