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

Twenty-six stages, each resumable, each writing its own outputs:

1. **`crawl_catalogue.py`** — the 13 index pages → `documents.csv`,
   `document_listings.csv`.
2. **`fetch_extract.py`** — each PDF → gzipped plain text in `data/text/`,
   plus `text_extraction.csv`.
2b. **`fetch_basemap.py`** — Natural Earth's `ne_50m_land` shapefile → the
   simplified coastline in `data/reference/world_land.geojson` (§5o). Run once;
   the result is checked in, so no later stage touches the network.
3. **`parse_ties.py`** — text → `affiliations.csv`, `org_affiliations.csv`,
   `company_attributes.csv`, `doc_references.csv`.
3b. **`parse_person_index.py`** — inverted indexes → person → company ties
   the dossier parser cannot see (§2b).
3c. **`parse_prose.py`** — boards reported in running prose (§4d).
3d. **`resolve_annotations.py`** — the compiler's inline affiliation notes,
   resolved against the company list (§4e). Needs `companies.csv`, so it runs
   after a first pass of stage 4.
3e. **`parse_biographies.py`** — biographical dictionaries (§4f). Also runs
   after a first pass of stage 4.
3g. **`parse_mandates.py`** — deputies and senators named anywhere in the
   corpus (§4j). Adds no ties; writes `person_mandates.csv`.
3h. **`parse_rosters.py`** — the compiler's five parliamentary directories
   (§4i). Also runs after a first pass of stage 4.
3i. **`parse_offices.py`** — offices of state and the colonial administration
   (§4k). Adds no ties; writes `person_offices.csv`.
3j. **`parse_person_dossiers.py`** — the catalogue's 240 entries on
   *individuals*, read from the person's side (§4l). Also runs after a first
   pass of stage 4, because it resolves companies against `companies.csv`.
4. **`build_network.py`** — observations → nodes, edges, projections, GraphML.
   All seven genres are merged by default; `--no-person-index`, `--no-prose`,
   `--no-annotations`, `--no-biographical`, `--no-roster` and
   `--no-person-dossier` drop one each.
5. **`split_by_country.py`** — dataset → per-territory bundles (§5b).
6. **`code_positionality.py`** — people → colonial/native coding (§5c).
6b. **`centrality.py`** — interlock graph → exact betweenness per firm (§5e).
6c. **`geocode.py`** — addresses → a city per firm, below colony level (§5f).
7. **`make_figures.py`** — network → the core figures, HTML and SVG (§5d).
8. **`make_territory_figures.py`** — network → the whole-empire figure, the
   territory matrix and one figure per territory (§5d).
9. **`render_png.py`** — every figure → PNG, one network per file.
10. **`make_geo_figure.py`** — places → the interlock network on the map (§5f).
11. **`make_descriptive_figures.py`** — the ten non-network figures (§5g).
12. **`make_network_figures.py`** — the ten structural figures, plus
    `network_measures.csv` (§5h).
13. **`make_node_figures.py`** — the six node-level figures, on the drawing
    primitives in `draw.py` (§5i).
14. **`make_legislative_layer.py`** — mandates × the company network →
    `legislators.csv`, the legislator interlocks, the roster continuity (§5j).
15. **`make_legislative_figures.py`** — figures 34–39 (§5j).
15b. **`sectors.py --sync`** — the source's 109 sector labels → the
    19-group mapping in `data/reference/sector_groups.csv` (§5l).
16. **`code_political_connections.py`** — offices × boards →
    `company_political.csv` and its two summaries (§5k). The rules are in
    `data/reference/political_connection_rules.md`, and the sector
    cross-tab (§5l).
17. **`make_political_figures.py`** — figures 40–46 (§5k, §5l).
18. **`code_sector_centrality.py`** — the interlock graph × the sector
    grouping → `sector_centrality.csv`, `edges_sector_interlock.csv`,
    `sector_centrality_baseline.csv` (§5m).
19. **`make_sector_network_figures.py`** — figures 47–52 (§5m).
20. **`place_on_map.py`** — the placement ladder →
    `company_map_positions.csv`, `territory_anchors.csv`,
    `map_tie_geography.csv`, `map_geography_baseline.csv` (§5n).
21. **`make_world_map_figures.py`** — figures 53–56 (§5n).
22. **`make_period_map_figures.py`** — the map split on the five periods:
    figures 57–58, five full-width maps in `figures/by_period/`, and
    `map_period_summary.csv` (§5p).
23. **`audit_coverage.py`** — a diagnostic: what the documents that yield
    nothing actually are, sorted by register and by territory (§4m). Adds no
    ties and changes no network file.

Figure stages 7, 8, 11–13, 15, 17, 19, 21 and 22 take `--lang en`, which writes a parallel `figures/en/`
tree with the territory, region and sector labels in English. Firm and person
names are left in French throughout: a company's name is a legal name rather
than a description, and an English rendering of it would be a string that
appears in no archive or authority file. The category vocabulary is a
description and is translated, in `data/reference/labels_en.csv` — 183 rows,
which `checks.py` asserts is complete against the data.

`checks.py` validates the parsers and the built dataset (1,362 assertions).

## 2b. What is *not* extracted

Extraction of the PDFs is near-complete: 5,867 of 5,920 documents (99.2%), the
rest dead links. Turning that text into ties is not.

Four denominators are easy to confuse, so they are stated once here and used
consistently: **5,920** documents are catalogued, **5,874** have a text file,
**5,867** extract cleanly, and **5,863** carry usable text — the four that fall
out hold under 200 characters, a header and nothing else. Tie coverage is
measured against that last figure. **3,686 of the 5,863 (63%) yield at least
one tie**; the other 2,177 hold 26% of the extracted characters. When only the dossier parser existed those figures were 2,482
(42%) and 47% — stages 3b–3e, below, are what closed the gap. This section
says what is still in the residue, because a reader is otherwise entitled to
assume the pipeline saw everything.

Sorting the 2,177 zero-tie documents by how much board vocabulary they
contain (the same counting rule as before, so the rows are comparable):

| Role words in the text | Documents | Was | Reading |
|---|---|---|---|
| none | 499 | 563 | genuinely no board data |
| 1–4 | 722 | 986 | a passing mention in prose |
| 5–24 | 792 | 1,307 | mostly honours lists and prose histories |
| 25 or more | 256 | 530 | a different genre the parsers do not read |

The last row is the real gap, and it is not one thing:

- **Inverted indexes.** The entry is a person and the list is of companies,
  keyed by number to a companion list. `parse_ties.py` cannot see these at
  all. Stage 3b now reads them — see §4c — and recovers 15,679 ties from
  `Annuaire Desfossés 1956` alone, a document that previously yielded zero.
- **Biographical dictionaries** (*Qui êtes-vous ? 1924*, *Légion d'honneur en
  Indochine*), where affiliations sit in a bracketed `[Administrateur : …]`
  block after fielded prose. Stage 3e reads these — see §4f.
- **Honours lists** (*Mérite agricole*, 1.1M characters). These score high on
  role vocabulary but carry *occupations*, not directorships — "propriétaire
  et colon", "vétérinaire à Oran". Correctly excluded; counting them would
  inflate the network with ties that do not exist.

One further gap is quantified elsewhere: **9,942 parsed ties (13.1%)** are
dropped for want of an identifiable firm (§5). The compiler's annotation leads
are now resolved as far as they go (§4e).

### A genre measured and left out: the compiler's footnotes

One further register was built, measured, and **deliberately not merged**. The
compiler footnotes the men he knows about, in a fixed shape — the name, life
dates in parentheses, a colon, then the career in prose:

    Paul Bayard (1852-1931) : polytechnicien, ingénieur aux forges de Pompey,
    directeur des Forges et clouteries réunies à Charleville …

There are 8,872 such headers across the corpus and none of the six shipped
parsers can read them: the heading is a person and the text is prose, so the
dossier parser has no firm to hang a list on; the prose parser needs an inline
`M.` marker the footnote never repeats; the biographical parser wants the
dictionary header form (capitalised surname, parenthesised forename) and three
bracketed role blocks before it will look at a document. `src/parse_footnotes.py`
supplies the header pattern and borrows stage 3e's machinery for everything
else. It yields **5,172 ties, 1,690 people, 1,511 firms**.

It is in the repository, it is not in the network, and it is not switched on by
any flag. A 15-row hand audit against source text put precision at **8–9 of 15
(≈55–60%)**, against the 90–97% the shipped genres measure. Two failure classes
account for it:

- **Non-person headers with the footnote's shape.** `À l'origine du Comptoir
  technique algérien (1917) :` is a narrative sentence; `Conseiller du commerce
  extérieur (1932) :` is an office. Both parse as a surname. The module's
  `NOT_A_PERSON_RE` rejects decorations ("Chevalier de la Légion d'honneur
  (1911) :") and misses these.
- **Role words and institutions resolved as firms.** The company resolver
  matches on content words, so the bare role `président` found a firm literally
  named *Président*, and `l'observatoire de Phu-Liên` resolved to the
  *Observatoire central magnétique*. A `PUBLIC_OFFICE_RE` already drops 175
  phrases of this kind per run; it is not enough.

Both are fixable and neither is fixed here. The rule this project holds itself
to is that a genre ships when its measured precision sits in the band the
others occupy, and this one does not, so the honest record is the module, the
number, and the two named defects — not 5,172 ties of unknown quality folded
into a dataset whose error rate is published.

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
`Van Nierop`), and the two ways the compiler restores a forename the source
abbreviated — expanding an initial in place (`G[eorges] Hersent`) and
supplying the whole name ahead of the surname (`[Charles] Michel-Côte`).

Those two conventions were, for most of this dataset's life, thrown away. The
rule accepted only parentheses, `P(aul) Delorme` — a form that occurs **zero**
times in the corpus — while the bracketed form occurs 7,802 times and the
leading form 7,388. All 15,190 were read as annotations and discarded, which
matters more than a lost forename: the person splitter below works from
exactly this evidence. Recovering them raised the share of ties carrying a
full forename to 47%. The leading form is the ambiguous one, since
`[Phosphates] Océanie` has the same shape, so the bracketed word must be an
attested forename before it folds in.

Two refusals are deliberate. After an honorific, a name followed by a
particle is **not** split — `baron Carton de Wiart` keeps `Carton de Wiart`
as one surname, where the positional fallback would have made "Carton" a
forename. And an unrecognised first token followed by a particle is left
inside the surname, so `Carlos de Barros Soares Branco` becomes one surname
rather than a guess.

`person_key` = normalised surname + first given initial (`fontaine-a`).
`build_network.py` then resolves it in **both** directions, and records every
decision in `person_resolution.csv`.

**Folding**, for keys that are too fine. A surname-only key is merged into a
surname-plus-initial key when that key is unique for the surname *and* the
combined observation years fit within a 60-year career. `Katz` folds into
`katz-m`; it would not if an `E. Katz` also existed, nor if the years implied
a 90-year career. Refusals are recorded as `unfolded_ambiguous` or
`unfolded_year_span`.

**Splitting**, for keys that are too coarse — which is what the key format
otherwise gets wrong, and it was the largest known defect in this dataset.
Because the key carries only the first *initial*, Georges Hersent and Gilbert
Hersent were one node, and every firm one of them sat on appeared to interlock
with every firm the other sat on. Measured on the variant lists, **619 person
nodes (1.8%) merged forenames that cannot belong to one man, and they carried
7.0% of all observations.**

Where a key's observations name two such forenames, each named observation
moves to its own key (`hersent-g-georges`, `hersent-g-gilbert`) and the
initial-only observations stay behind on `hersent-g`, which now means "a
G. Hersent, unresolved". They are **not** handed to the commoner of the two,
for the same reason an ambiguous fold is refused: a coverage gap beats a
fabricated identification.

Two forenames count as incompatible only when **both are independently
attested in the forename reference list** and neither is a prefix or a
one-edit variant of the other. That guard is what makes the split safe, and
two cases show why it is needed. *Anathase* and *Athanase* Roudy are one man
— the compiler himself writes "[Athanase, dit souvent] Anathase" — and a
transposition is not caught by an edit-distance test. *Démétrius* and
*Dimitri* Zafiropulo are one man under two transliterations of a Greek name.
Neither pair is two entries in the list, so neither splits. Splitting one man
into two nodes is the more damaging error, so the rule errs towards leaving a
key merged: it declines `Charles`/`Clifford` Michel too, where the two
probably *are* different people.

The effect is to remove interlocks that never existed, with no observation
lost — every tie is still present, merely attributed to a narrower node.
Measured on its own, against the same input, the split removes **5,682**
interlock edges. The net change to the built network is smaller, **2,940**,
because the forename recovery described above lands in the same release and
pulls the other way: it collapses keys such as `hersent-ep-anne-marie-thomas-j`,
built from a kinship note the parser had folded into a surname, back into the
real person, and those merges create edges of their own.

**What this still does not do.** Two contemporaries who share a surname *and*
a forename remain one node, as do two who are only ever named by initial. The
countermeasures available to you are `given_variants`, the year span on every
person node, and `person_resolution.csv`, in which every fold and split is
reversible.

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

## 4c. Reading the inverted indexes

`src/parse_person_index.py` handles the genre §2b identifies: the entry is a
person, the list is of companies, and the companies are numbered rather than
named:

```
Achard (Georges-P.), 107 (dga BAO), 207 (Bq comm. afr.), 238 (Créd. fonc.
    Ouest-Afric.), 1776 (Cult. Diakandapé).
```

The numbers key into a companion document that lists the firms in order —
`107. Banque de l'Afrique occidentale` — so the pair is a complete, resolvable
affiliation dataset. It produced **15,679 person ties plus 452 corporate ties,
9,111 people and 1,889 firms** where the dossier parser produced none.

**The trap.** Entries carry bracketed notes, and those notes contain numbers:
`Abinal (Patrice)[1883-1961][ing.-conseil…], 1613 (…)`. The life dates 1883
and 1961 are both valid company numbers, so a naive scan turns them into
directorships that are entirely plausible and entirely invented. There are
2,628 numbers inside brackets in that one document. Bracketed spans are
therefore removed before any number is read, and a reference is accepted only
in list position.

Removing them is itself delicate. The document contains exactly one unmatched
`[`; a regex that pairs it with the next `]` deletes **87% of the file**, which
presents as a clean parse of a much smaller source rather than as an error. A
bounded, depth-counting scan replaces the regex, and `checks.py` tests both
failure modes directly.

**How the result is verified rather than asserted.** Most references carry the
compiler's own abbreviation of the firm — `107 (dga BAO)` — which is an
independent statement of what the number means. Every glossed reference is
scored for token overlap against the name the key gives. Agreement is **97%**;
a misaligned numbering would collapse it, and `checks.py` enforces a floor of
0.90. Roles come from the same gloss, with abbreviations peculiar to this
source: `comm. cptes` is a statutory auditor, not a director, and 2,461 rows
turn on that distinction alone.

**Scope: merged, and what that changes.** `Annuaire Desfossés 1956` lists the
companies quoted on the Paris Bourse. A large share of colonial firms were
publicly quoted, so this is a colonial source — excluding it to avoid
admitting some non-colonial firms would drop real colonial boards. It is
therefore merged into the network by default.

The consequence must be stated plainly: **this is no longer a purely colonial
universe.** 1,889 firms enter from the annuaire, of which 11% also have
dossier evidence; the remainder are metropolitan and foreign companies. That
is not noise — it is the rest of the portfolio of the same directors, which is
what an interlocking-directorate study wants — but a reader who assumes every
node is a colonial enterprise will be wrong. Every observation and every
two-mode edge carries `source_genre`, so filtering to `dossier` recovers the
previous scope exactly, and `build_network.py --no-person-index` rebuilds
without it.

Two further asymmetries follow from merging one dense source into many sparse
ones. The annuaire is a **complete snapshot of one year (1956)**, where the
dossiers are scattered extracts across a century: the 1945–62 period therefore
has far better board coverage than any other, and a time series of density or
degree across periods is measuring the sources as much as the economy. And
because a complete board list generates every pair among its members, the
annuaire contributes interlocks at a rate the dossier evidence cannot match.
Compare periods with `source_genre` held constant, or not at all.

### The bug that merging exposed

The first merge produced 162,349 interlocks, 122,693 of them in 1945–62. That
spike was not a finding. `parse_person_name` reads `Baert (J.)` backwards —
"Baert" as the forename, "J." as the surname — because in the dossier genre
that shape is genuinely ambiguous. In *this* genre it is not: the format is
`Surname (Given)` throughout. So 148 distinct people collapsed onto the key
`j-b`, which then held 119 board seats and generated some 7,000 interlock
edges between firms that never shared a director.

Stage 3b now parses the name with the format it is guaranteed rather than
inferring it, and moves a trailing particle to the front — `Abs (P. d')` is
P. d'Abs, not a person called "P. d'". Distinct people went from 3,929 to
9,111 and the most-seated individual from 119 boards to 26. `checks.py` tests
that four different B-surnames with the initial J. produce four different
keys, because that is the assertion the bug violated.

### A bug this stage exposed in `org_key`

`org_key("Anciens Établissements Ch. Peyrissac et Cie")` returned an empty
string. The rule that strips a trailing predecessor clause — "(anciennement
Société X)" — ends in `.*$`, so on a name that *opens* with that vocabulary it
matched at position 0 and consumed the whole name. Peyrissac is a substantial
AOF trading house and lost 72 observations to it. The same pattern matched
`anc` inside "Bl**anc**" and `ex` inside "Al**ex**.", truncating those names
mid-word.

The rule now fires only when real name text precedes it, and a name made
entirely of legal forms falls back to a slug of the whole string — except
where that slug is *itself* only a legal form ("Société"), which stays
unkeyed rather than becoming a node several unrelated observations pile into.
Twenty company identifiers changed, all of them corrections; 36 previously
unkeyable firms now resolve.

## 4d. Boards reported in prose

Most of this collection is press extracts, and the press reports boards in
sentences, not lists:

> Les administrateurs sortants, MM. le comte de Germiny, J. Stewart,
> G. Alberti, J. Alexander, ont été réélus.

`parse_ties.py` will not touch that, by design — an early version triggered on
the bare phrase *conseil d'administration* wherever it appeared and produced
thousands of directors out of ordinary sentences. `parse_prose.py` reads the
prose with three conditions required together: an explicit person marker
(`MM.`, `M.`, or an appointment verb), an explicit role word in the same
clause, and every candidate name passing the same shape test the structured
parser uses. It yields **14,305 ties over 2,523 firms**, of which 8,421
person-firm pairs are new.

**Attribution was never the hard part.** For a firm dossier the subject
company is the catalogue title, which the segmenter already carries. The
missing piece was only finding the people.

**Precision is the hard part, and it is measured rather than assumed.** Random
samples were hand-checked against their source context, in three rounds. The
first scored roughly 70%, the second 75%, the third around 90%. Each round
named a specific failure, and each is now a regression test:

| Failure | Example | Fix |
|---|---|---|
| Singular role applied to a whole run | "MM. Meunier, Guibal, Godard, Billiard, président" made four presidents | A singular role binds the last name only; a plural one binds the run |
| Non-compete clause read as appointment | "s'interdisent de diriger comme gérants, directeurs" | Negated clauses reject the match |
| Decoration read as a person | "M. Nunzi, commandeur de la Légion d'honneur" | Honours vocabulary rejected |
| Address read as a person | "demeurant à Paris, 10, rue de Laborde" | Street vocabulary rejected |
| Meeting chair read as board president | "sous la présidence de M. Louis Martin, maire" | Requires "président du conseil" |
| Occupation between name and role | "M. Willot, inspecteur général des Postes, président" | An occupation in the run rejects the match |
| Truncated names | "sous la présidence de M. Albert Thomas" yielded "Alb" | Lazy quantifiers given explicit terminators |

Two caveats on that figure. It comes from samples of twenty, so it locates the
right order of magnitude and not a second decimal place. And "correct" was
judged against the surrounding sentence, which establishes that the text says
what the parser recorded — not that the source was right.

**This stage is in the default network**, and every row is tagged
`source_genre = "prose"` so `--no-prose` (or a filter on the built edge list)
recovers the structured-only network exactly. Merging it is the right default
because the alternative is worse: press extracts are the bulk of this
collection, and excluding them meant excluding most of what the compiler
actually assembled. The ~90% precision is a real cost and is why the tag
exists on every row rather than only in this document. That 23% of its rows
independently corroborate a pair the structured parser already found is a
useful signal: noise would not concentrate on pairs another method also
produced.

## 4e. The compiler's own affiliation notes

Board lists carry the compiler's identification of a director's *other* seats,
beside the name: `A. R. Fontaine (Distill. Indoch.)`. That is interlock
evidence stated by the source. Stage 4 emits 21,904 of these as candidates and resolves 3,680 of them
(16.8%) directly — exact names and catalogue acronyms — because the note is
abbreviated where the company name is not.

`resolve_annotations.py` matches by **token prefix, in order**: every note
token must prefix a name token, and in sequence. "Cotonn. St-Quentin" resolves
to *Cotonnière de Saint-Quentin*; "Bq de Madagascar" to *Banque de
Madagascar*. Prefix matching needs no list of abbreviations, which matters
because the compiler invents them freely. Result: **1,646 ties over 502 firms**,
hand-audited at roughly 94%.

Three refusals do most of the work for precision. A note matching several
firms is dropped rather than resolved to the likeliest — "Mines" prefixes
dozens of names, and choosing one manufactures a specific, checkable, wrong
claim. A single token resolves only on an exact whole-name match, because
"Armand" prefixes *Armandon & Cie* and "Zafiropulo" prefixed an unrelated
agency. And a note that is a territory is never a firm: "Afrique Équatoriale
Française" was matching *Société Générale Française de l'Afrique équatoriale*.

The stage also filters out target company nodes whose "name" is really a
biographical fragment — the parsers occasionally promote a prose span, and
matching against one such node turns a single bad node into many bad ties.
Writing that filter reproduced a bug already documented in `names.py`: under
`re.IGNORECASE` a `[a-z]` character class matches uppercase too, so a rule
meant to catch lowercase openings rejected *every* company name in the file,
including the Banque de l'Indochine. `checks.py` now pins five real names
against it.

Two resolution rates appear above and they measure different stages, which is
worth keeping straight. Stage 4 resolves **3,680 of its 21,904 raw candidate
rows (16.8%)** by exact name and catalogue acronym. Stage 3d then runs the
prefix matcher over the **20,354** distinct notes that remain and recovers
**1,676 (8%)** more.

Why that second rate is so low: 4,218 of those notes name the firm the
observation already belongs to, and 8,242 name a company absent from this
corpus — many are
metropolitan firms the collection never covers. Neither is recoverable by
better matching.

Merged by default and tagged `source_genre = "annotation"`; `--no-annotations`
drops it. Two properties are worth keeping in view when using these rows: the
tie is the compiler's assertion rather than a transcribed board list, and it
carries no year of its own beyond the observation it sits beside.

## 4f. Biographical dictionaries

*Qui êtes-vous ? 1924* and *Légion d'honneur en Indochine* are person-indexed:
a name in capitals, fielded prose, and a bracketed block of affiliations the
compiler added. None of the three earlier parsers can read them.
`parse_ties.py` wants a board list under a firm heading; here the heading is a
person. `parse_person_index.py` wants numbered references; here the companies
are named. `parse_prose.py` wants an inline `M.`/`MM.` marker; here the person
is the entry header and is never named again.

What stage 3e adds is **person-scoped segmentation**: the document is split at
the capitalised surname headers, and every role construction inside an entry is
attributed to that entry's person. Company names are resolved with the prefix
matcher from §4e. **3,167 ties over 725 firms and 696 people**, hand-audited
at roughly 93%.

Two guards were added from the audit. A capitalised *headline* has exactly the
shape of an entry header — "UNE ROSETTE BIEN PLACÉE (L'affaire)" was read as a
person — so headers containing ordinary French function words are rejected.
And a single generic token is not a firm: "Compagnie du port" reduces to
*port* and matched a company literally called *Port*; "Coloniale" matched *La
Nouvelle Coloniale*. That fix improved §4e as well.

**These ties carry no year**, and `checks.py` asserts it. A biographical entry
gives a career, not a board as it stood in a given year, so these edges land
in the `undated` slice and no period slice can place them. They are merged by
default — the pooled network is where they belong, and dropping a whole genre
to protect the period slices would cost more than it saves — but any analysis
that turns on timing should filter them out with `--no-biographical` or on
`source_genre == "biographical"`.

## 4g. Board lists the punctuation did not reveal

Every trigger in §4 ends with a colon or a dash — `Conseil d'administration :`,
`Administrateurs. —`, `Cons. d'adm. :` — and the list it introduces is taken as
a window after that punctuation. A large family of directories does not
punctuate at all. It prints the heading bare on its own line and the board
one member per line, surname first, forename parenthesised, address after the
comma:

```
Conseil d'administration
composé de 3 à 6 membres, nommés pour 3 ans, propriétaires de 50 actions.
ASSIS (Henri), à Oran ;
GERMAIN (Pierre), 1, r. Élisée-Reclus, Alger ; pdt, adm. délégué ;
COMMISSAIRES AUX COMPTES
DEBULLOIS (Pierre), à Oran.
```

Two separate rules discarded this. No trigger matched a heading with nothing
after it. And `looks_like_name_list` — which splits a candidate body on `;` and
`,` and asks what share of the parts are name-shaped — reads the comma between
a name and its *address* as a name separator, so a six-member board splits into
twenty-odd parts of which five are names, the ratio fails, and the whole list
is thrown away.

**This was the largest remaining extraction gap in the corpus.** 14,314 lines
of this shape across 901 documents; 128 of the 283 Tunisian documents with text
yielded no ties at all, including *Salines de Tunisie* (88k characters),
*Frigorifique de Tunis* (62k) and *Union ovine de l'Afrique du Nord* (240k).
The single biggest instance is the Crédit foncier d'Algérie et de Tunisie's
*Annuaire des valeurs de l'Afrique du Nord*, which is why Algeria, Tunisia and
Morocco were the worst-covered territories in the network.

**What was added.** Eight bare headings as triggers (`Conseil
d'administration`, `ADMINISTRATEURS`, `Commissaires aux comptes`, `Conseil de
surveillance`, `Censeurs`, `Direction`, `Gérants` and their capitalised forms),
and a line register — `LINE_MEMBER_RE`, `parse_line_list` — that reads one
member per line and reorders `ASSIS (Henri)` into the `Henri Assis` the name
parser expects. The reordering is done explicitly rather than left to
`_make_member`'s surname-first fallback, which only folds the parenthetical
back when it recognises a forename: `LEDOUX (F.)` came out under the key
`ledouxf`, and `de SINCAY (F.)` was dropped entirely because a lowercase
particle broke its all-caps test.

**Bounding a list that has no punctuation.** A first pass gave the bare
headings the same fixed 1,600-character window the punctuated triggers use, and
hand-checking put precision at **11 of 15** — the window ran past the board into
a staff roster (`D. CAPELLE, chef-comptable`), a footnote biography, and in one
case a marriage announcement. The run is now walked line by line and stops at
the first line carrying neither a comma nor a semicolon. Every genuine member
line in this corpus has one or the other; the headings that end a list
(`Comité de direction`, `DONNÉES FINANCIÈRES`) have neither. Blank lines and
the stray footnote digits the PDFs drop between members sit *inside* the run
rather than ending it.

**Precision after that change: 13 of 14** on a fresh random sample checked
against source context, which is the band the other genres occupy (§4c–4f). The
one failure is the residual defect below.

**One defect this did not fix.** A member's town, printed between his name and
his role — `Charles Gimon, Levallois-Perret ; v.-pdt` — is split off by the
comma register and recorded as a separate director. The parser has always
rejected fragments that name a place, but its list and the geocoder's
gazetteer were maintained separately and the gazetteer knew 81 cities the
parser did not; they are now one authority (`common._gazetteer_cities`), which
narrows the class without closing it. A single-token member with no forename is
the shape to distrust.

**What it recovered.** Affiliations 73,137 → 75,335 at the time; the register
is now one of several read by §4h as well. Tunisian documents yielding at
least one tie went 155 → 172, taking the territory from 55% to the corpus
average.

## 4h. The constitution notice, and where a list ends

§4g read the board lists that carried no punctuation. Auditing the residue
that still yielded nothing — 2,221 documents with usable text — turned up one
more register and, more usefully, three ways every existing trigger was
overrunning its list.

**The register.** A company's constitution notice states the first board as a
completed act, with the names after the verb and anything from nothing to a
whole clause in between:

```
Ont été nommés administrateurs : MM. Maurice Tricon, Maurice Petit
Ont été nommés administrateurs statutaires pour trois ans : M. le chevalier …
Ont été nommés administrateurs de cette société MM. Camille Barrère, …
```

`conseil_nomme` wants the words "conseil d'administration", which this
register never uses. 590 occurrences, 46 of them in documents that yielded no
ties at all. The companion form — `Les premiers administrateurs *de cette
société* sont …` — was missed by a trigger that allowed no words between the
noun and the verb.

**Where a list ends.** Hand-checking the first 1,960 rows the new trigger
produced gave **10 of 14**, and every failure had the same shape: the body ran
past the members into what followed. Three terminators were missing, and none
of them was specific to this trigger — each had been letting *every* list in
the corpus overrun:

| what leaked in | the member it produced |
|---|---|
| the source citation, written as a dash rather than a parenthesis — `… rue de Saint-Pétersbourg, 24. — Loi, 7 mai 1900.` | a director named **Loi**, which is the legal gazette |
| a compiler footnote about one of the members — `Paul Bayard (1852-1931) : … directeur des Forges et clouteries réunies à Charleville` | a director named **clouteries réunies à Charleville** |
| a residence clause trailing an address — `demeurant en ladite ville, résident actuellement à Paris` | a director named **résident actuellement à Paris** |

**Four fragment defects, three of which corrupt the key.** A footnote marker
glued to the last member after a period (`Fernand Raty. 1`); the same marker
with no period at all (`Émile Alcan2` — 82 rows, and `alcan2` is a *different
person* from `alcan-e`); the compiler's elision marker inside a quoted list
(`MM. … Eugène Guët…` — 177 rows); and a leading conjunction, because
`_split_names` splits on `" et "` with whitespace both sides and so can never
match at position 0 — the last member of every `A, B, et C` list in the corpus
was recorded as `et C`. Between them, **239 distinct person keys** were
fragmenting real people into duplicate nodes.

**Precision after those fixes: 9 of 14 verified correct, 0 wrong**, the
remainder being rows whose source line the audit could not locate. The
newspapers, firms and clauses are gone.

**What is still not read.** The largest remaining seam is the compiler's own
career footnotes — `Administrateur de l'Omnium d'entreprises, à Paris (1911),`
followed by a URL to that firm's dossier. 2,462 of them, in 869 documents, 147
of which yield nothing at all. The *company* resolves exactly from the URL,
which is better evidence than any name match in this pipeline. The *person*
does not: recovering them needs footnote-scoped segmentation, and attributing
a directorship to the wrong man is a worse outcome than not extracting it.
Left unbuilt deliberately.

## 4i. The parliamentary rosters

`src/parse_rosters.py` reads eight documents, and they are the only eight in
the corpus that are *about* the overlap between the legislature and the company
boards. The compiler filed them himself, under a group heading of his own
making: *Parlementaires intéressés directement ou par des proches à des
entreprises privées*. Five are Roger Mennevée's directory *Parlementaires et
financiers*, for 1924, 1930, 1932, 1936 and 1954; the others are a press survey
of the 1893 intake, *Les squales coloniaux* (1922), and one on the Belgian
parliament.

**They were almost unread.** The 1924 volume is 89,259 characters and yielded
**4 ties**; the 1954 volume is 46,229 characters and yielded **1**. The cause
is a comma. Stage 3e segments entries on `SURNAME (Forename)` and Mennevée
writes `SURNAME, Forename`:

    D'ANDIGNÉ, Geoffroy (Comte)[1858-1932]
    Député de Maine-et-Loire [1924-1932]
    Adresse : Hôtel d'Orsay, 9, quai d'Orsay, à Paris (VIIe).
    Administrateur :
    Compagnie parisienne de garages automobiles (nommé à l'assemblée du 7
    juillet 1922).

So every entry in three of the five directories fell through, and the
`Administrateur :` block under it with them. This stage adds a header rule that
covers both that fielded form and the running-prose form the 1924 and 1954
volumes use, and the discriminator in both cases is the same: a chamber word
within 200 characters of the name. That word is what makes a capitalised line a
roster entry rather than a headline, and it is *also the mandate*, which makes
this the only genre that yields a seat and a directorship together.

Result: **1,096 entries, 995 with a constituency, 541 with a term**, and **587
ties** to firms the catalogue holds. The 2,393 company phrases that do not
resolve are mostly real firms that are simply not colonial — *Sucreries et
raffineries d'Erstein*, *Chaux et Ciments de Chanaz* — and are correctly
absent.

**"ou par des proches" is in the group's title, and it is the precision
problem.** Mennevée tracks the proxy holding as carefully as the direct one, so
an entry is part career and part genealogy, and the companies in the genealogy
are not the parliamentarian's:

    Frère cadet de Paul-Jonas et Gaston Hesse, gérants des Comptoirs Hesse
    belle-mère de Lucien Bach, administrateur de la Société générale foncière
    Père de François André-Hesse, administrateur de la Société générale foncière

Reading those as the deputy's own directorships would manufacture exactly the
interlocks the source is careful to distinguish. Every role phrase is therefore
tested against the *clause* it sits in — back to the nearest `.`, `;` or
bracket edge, not the whole note — and a kinship word there redirects the tie:
`held_by` becomes `relative`, the person becomes the relative, and `related_to`
records the parliamentarian it was reached through. Clause scoping is what lets
`[ép. Potin. Anc. député de la Nièvre]` through, because Heuzey married a Potin
*and* sat for the Nièvre and the full stop says so. **31 of the 587 ties are
proxy holdings**, and `build_network.py` excludes them: they are counted in the
legislative layer, where the prête-nom structure is the object of study, and
kept out of the main network, where they would assert a seat the source places
one step away.

**Precision.** Two audits, because two things can go wrong independently.
Attribution — is the company phrase inside the entry of the man it was credited
to — measured **30 of 30** on a random sample checked against each holder's own
entry body. Resolution — is the resolved firm the firm the phrase named —
measured **23 of 25**, both failures being catalogue *section headings* matched
as if they were companies (`Société générale d'armement` → `ARMEMENT`,
`charbonnages` → `CHARBONNAGES`), which a rule now rejects. Getting there took
five iterations, and the defects are worth naming because each was a whole
class rather than a one-off:

- **Missed headers donate their boards upward.** `De WENDEL, François` went
  undetected because the particle is capitalised and the pattern was
  lower-case-only, so de Wendel's entire board was credited to Georges Weill,
  the entry above his. Albert Lebrun's 1936 entry names no chamber at all — by
  then he was President of the Republic — so it now ends the entry above it
  without opening one of its own.
- **Non-person headers.** `Paris, le 11 juillet 1924.` is where a letter was
  written; `Caoutchoucs de Phuoc-Hoa (1927)` is a firm; `Nos Députés` is a
  section heading whose own word is the chamber word that confirmed it;
  `Succursale : … Lille (Nord).` parsed as a man called Nord Lille.
- **A comma inside a company name.** `Association industrielle, commerciale et
  financière` became a firm called *commerciale et financière*, which resolved
  to a bank. A new board never starts with a lower-case word, so a fragment
  that does is glued back on.
- **The block that would not end.** Bounding an `Administrateur :` list only at
  the role labels this stage keeps let Raymond Patenôtre's run on through
  `Propriétaire des journaux : Le Petit Niçois, Le Petit Var, La Sarthe` and
  make him a director of three newspapers and of a company called Sarthe. Any
  `Label :` now ends the block — and the label's own spacing is the compiler's
  typesetting, non-breaking spaces included, which is why that rule took two
  attempts.
- **The relative is the last name in the clause, not the first.** "Sa fille
  Lina a épousé en 1930 le banquier Jean Rheims, administrateur des
  Manufactures indochinoises de cigarettes" is Rheims's directorship, and the
  first pass gave it to Lina.

The Belgian volume is excluded. The men are real and the boards are real, but a
seat in the Chambre des représentants is not a seat in the body that legislated
for the French empire, and the column would silently mean two things.

## 4j. Mandates, everywhere else in the corpus

The rosters are eight documents. Deputies and senators are named **9,692 times
across 1,415 of the other 5,855**, and not one of those mentions is a tie, so
no affiliation parser records any of them. `src/parse_mandates.py` reads them
into `person_mandates.csv` — **2,444 mentions, 1,117 people** — and changes the
affiliation network not at all. A directorship held by a sitting
parliamentarian is a different object from one held by an engineer, and the
mandate is what tells them apart.

Four registers carry a mandate, and they differ in where the subject sits
relative to the title: apposition (`M. Ernest Outrey, député de la
Cochinchine`), the compiler's bracket (`Camille Krantz* [député d'Épinal
1891-1910, CNEP]`), title-first (`le sénateur Ernest Feray`), and the career
clause of a footnote whose header is the person (`Jules Bozérian (1825-1893) :
avocat, député (1871-1876), puis sénateur (1876-1893) du Loir-et-Cher`).

**The kinship trap is the whole precision problem, again.** The compiler is a
genealogist as much as a company historian, and the mandate beside a name is
very often not that man's:

    Maurice Piot [fils de Léon Piot (1845-1922), député de l'Aude 1876-1877]
    Ch. Riotteau [fils du sénateur-maire de Granville Émile Riotteau]
    Marié à Geneviève Mérillon, fille d'un député de la Gironde

Reading these would seat three men in a chamber none of them entered. The same
clause-scoped kinship test as §4i handles them, and one more rule joins it: the
compiler's own disclaimers. `R. Carcassonne : probablement à distinguer de
l'avocat Roger Carcassonne, sénateur socialiste (1946-1971)` asserts precisely
what a naive read would deny.

Four further rejections earn their place:

- **`député` also means "delegate".** `G. L. (député), député au convent
  1930-1931 de la Loge L'Étoile flamboyante` is a masonic lodge.
- **Foreign chambers.** `le commandeur docteur Enrico Scalini, sénateur du
  Royaume` sat in the Italian Senate.
- **A year near a title usually dates something else** — the clipping it
  appears in, the budget under debate, the election the man lost: `député, sur
  le budget du ministère de la marine pour 1889`; `CHAGNAUD Léon, sénateur de
  la Creuse, non réélu en 1929`. A term of office is written as a term of
  office: bracketed after the title, or as a span. A bare single year is not
  read, which loses `Élu député de la Corrèze en 1893` and is the right trade.
- **The constituency slot is anchored, not searched.** `député, vice-président
  de la Commission des Colonies` is not a deputy for the Commission des
  Colonies, and `sénateur du Nord` followed by the article title *L'Afrique
  Équatoriale Française* is not a seat called Nord L'Afrique.

**Precision: 18 of 18 correct on person and chamber** in the final audit round,
with every constituency also correct; an earlier round measured 19 of 20 on the
same criterion, the exception being a name that had absorbed the end of the
preceding sentence (`26, rue d'Athènes. Ferdinand Buisson, ancien député`).

Two things this file is not. It is not a parliamentary roster: a man who sat for
twenty years may appear once or forty times, so every consumer aggregates it.
And it is not checked against the Assemblée nationale's own biographical
dictionary — the constituency and the years are the compiler's, with his errors
intact.

## 4k. Offices of state, and the colonial administration

Stage 3g reads the legislature. `src/parse_offices.py` (stage 3i) reads the
executive, which in a colonial dataset is the larger half. The corpus names a
*gouverneur général* 15,595 times across 1,653 documents, a *résident
supérieur* 5,770 times, a *ministre des Colonies* 3,088 times. A board holding
a retired governor-general of French West Africa is connected to the colonial
state in a way no parliamentary mandate captures: in the territory the company
operated in, the governor-general **was** the state — he signed its
concessions, set the labour regime it recruited under, and allocated the land
it planted.

The subject-resolution machinery is stage 3g's, imported rather than copied.
"Whose title is this" has the same four registers — apposition, the compiler's
bracket, title-first, the footnote career line — whether the title is `député`
or `gouverneur général`, so `parse_mandates.subject_of` now serves both and the
kinship and disclaimer discipline of §4j applies unchanged.

**The reference trap is the new problem, and it is far worse than for a
mandate.** A chamber is almost only ever named as an attribute of a man. An
office is named overwhelmingly as an *institution*:

    autorisée par arrêté du gouverneur général du 14 mars 1923
    concession accordée par le ministre des Colonies
    Le Gouverneur général de l'Algérie à monsieur Treille, député, Paris

None of those attributes the office to anybody, and all three are the ordinary
way the corpus mentions it. The defence is that a row is emitted only when
`subject_of` finds a named subject, which requires a name-and-comma immediately
before the title, a bracket, or a recognised forename immediately after it. A
bare `par le gouverneur général` has none.

That is measurable, and it is the honest headline for this stage: `OFFICE_RE`
matches **46,344** times across the corpus and the stage emits **5,642 rows**
— **12.2%**. The other seven-eighths name an office without naming its holder.
Result: **2,415 people, 844 of them in the affiliation network**, across eight
office classes.

Four collisions needed rules of their own, because one word is two offices:

- **`administrateur`** alone is a company director, which is the rest of this
  dataset. Only `administrateur des colonies` and `administrateur des services
  civils` are the civil-service rank, so the qualifier is required and
  `administrateur délégué` never matches.
- **`gouverneur`** governs the Banque de France as well as Madagascar. A bank
  governorship is a state appointment but not a colonial one, so it is coded
  `state_bank`.
- **`ministre de France à Tanger`** and `ministre plénipotentiaire` are
  diplomatic posts, not cabinet seats, and are routed to `senior_state` by a
  negative lookahead on the minister pattern.
- **`préfet apostolique`** is a bishop. **Military rank** — `général`,
  `colonel`, `capitaine` — is not read at all: in this corpus those words are
  honorifics attached to hundreds of directors and would swamp every class.

Two defects worth recording because both were silent:

- **`(?i)` on a pattern containing `[A-Z]`.** The flag applies to the whole
  pattern, so the jurisdiction's capital-letter class matched lower case too,
  and `haut-commissaire de la République française par intérim` yielded the
  jurisdiction *République française par*. The flag is gone and the lower-case
  prefix words are spelled out.
- **A ministerial portfolio read as one letter.** `ministre des T` matched, and
  *ravaux publics et des* went into the jurisdiction column. The portfolio is
  now consumed whole, and its continuation is restricted to a capitalised word
  or one of the handful of lower-case portfolio adjectives — otherwise
  `ministre des Colonies a déclaré que` swallows the sentence.

**Precision: 20 of 20** on person and office class in the final audit round,
against source context. The one row a stricter reading would reject was a real
office correctly attributed to the right man — `sir Joseph Maclay, ministre du
Shipping` — but a *British* cabinet seat, which is a scope error rather than an
extraction error. A foreign-honorific guard now drops it.

`former` is read from the source's own wording, before the office (`ancien`,
`ex-`, `ci-devant`) and after it (`honoraire`, `en retraite`,
`démissionnaire`). **764 of 5,642 mentions** are former office-holders. Since
the compiler omits `ancien` far more often than he omits an office, that is a
floor.

## 4l. The dossiers on people, which are written inside out

Every reader described so far is **company-anchored**: find a board heading,
read the members under it. The catalogue also holds 240 entries whose subject
is a person — `entry_type = person` — and those are written the other way
round. The man is named once, in the entry's own title, and the body lists what
he sat on:

```
Administrateur de la Banque auxiliaire, Union parisienne et provinciale
Administrateur du comité de Paris de la Banque de Tunisie (mai 1886).
Administrateur délégué des Charbonnages du Tonkin (1895-1898).
```

Nothing was reading that shape, and the measurement is unambiguous: **a company
dossier yields a tie 67.2% of the time, a person dossier 21.3%**. The gap was
not that the documents were empty but that they were inside out.

This seam was found by disbelieving a claim in an earlier draft of this
document. §4g had brought Tunisia from the worst-covered territory to above the
corpus average, and the residue that still yielded nothing was written off as
books and honours lists. It is not: two of the silent Tunisian documents are
career blocks of exactly the shape above, and following that up corpus-wide
found the genre rather than the territory.

### The subject is free, which is what makes this genre cheap and safe

`parse_mandates` (§4j) and `parse_offices` (§4k) spend most of their code
deciding *whose* title a phrase is, because an office is named as an
institution far more often than as a man. Here the catalogue answers it: the
subject is the entry's `name_listed`, parsed by the same
`names.parse_person_name` every other stage uses, after the dates and the
compiler's gloss (`, banquier à Angers`) are stripped. A role line in the body
needs no subject resolution at all.

Two classes of entry the subject rule must refuse, and one test that did not
work:

- **Firms filed as people.** `Jacques Menasché & Cie (1926-1933), Paris` and
  `Tramways de Tunis (S.A. des)(1888-1901)` are `entry_type = person`.
  `names.looks_like_org` rejects them.
- **Institutions.** It does *not* reject `Bureau d'organisation économique
  (B.O.E.)`, which is tuned to company names — and that entry duly acquired a
  directorship of the Ciments libanais, `Bureau` having been read as a surname
  and `organisation économique` as a forename. `INSTITUTION_HEAD_RE` refuses a
  title beginning `Bureau`, `Office`, `Comité`, `Syndicat` and the rest.
- **The forename test could not be a list.** The obvious fix is to require the
  forename to be in `data/reference/forenames.txt`, and it fails: that list
  holds ~330 names and contains neither *Adolphe* nor *Adrien*. Requiring it
  refused 222 of 240 entries. The test is shape instead — a forename is one to
  three capitalised tokens — which refuses `organisation économique` and keeps
  `Adolphe`. A legal form in the forename slot is refused outright, which is
  what `Chaux hydrauliques et ciments d'Algérie (S.A. des)` is.

### The bug the checks caught, which nothing else would have

The catalogue writes `SURNAME (Forename)`, and `names.parse_person_name` reads
the **first** token as the forename: `parse_person_name("Noël (Octave)")`
returns `given = Noël`, `surname = (Octave)`, `person_key = octave-n`. The
first version of this stage passed the title straight in, so **every one of its
149 rows carried an inverted person key** — and the ties still merged, still
counted, and still drew, because an inverted key is a perfectly well-formed
key. Nothing in the output looked wrong.

`checks.py` asserts `subject_of("Noël (Octave)(1846-1918)")` has the surname
*Noël*, and that is what caught it. The title is now reordered into
`Forename Surname` before the parser sees it, exactly as §4g reorders
`ASSIS (Henri)`; the dates and the compiler's gloss are stripped first, so
`Brizon (Alexandre)(ca 1851-ca 1933)` and `Ogliastro (Antoine)(1875), puis
Louis Ogliastro` both resolve.

### The company side is stage 3d's resolver, not a new one

A role line names its company in the compiler's abbreviated register, so
`resolve_annotations.resolve` does the matching: prefix-in-order against
`companies.csv`, ambiguity dropped rather than guessed, place names refused.
**A line whose company does not resolve is not emitted** — 262 of them. That is
a deliberate recall sacrifice: an unresolved company name is a node the graph
cannot join to anything, so keeping it would raise the tie count without
connecting a single pair of firms.

### Two rules against crediting the wrong man

A dossier is biography, so it names the subject's family and the family's seats
in the same paragraph. The first version credited Eugène Haffner with the
Plantations Hallet on this passage:

```
… fils de Paul-Adolphe Chalamel (1839-1909),
administrateur du Palais Luxembourg. Directeur du Lycée franco-chinois de
Cholon, puis directeur général des Plantations Hallet. Voir encadré.
Remariée à Saïgon, le 14 octobre …
```

The seat is his son-in-law's. Two rules catch it, and both are needed because
the sentence containing the role names nobody:

- **`KINSHIP_RE` within 200 characters before the match** — the same rejection
  the roster parser makes in §4i, scoped by distance rather than by clause
  because these lines wrap mid-sentence. 54 rows removed.
- **`NEW_SENTENCE_RE` after the company on the same line** — a date or a short
  gloss is fine; a new sentence with prose in it (`. Voir encadré. Remariée à
  Saïgon…`) means the line was flowing biography. 22 rows removed.

### What it yields, and what it is worth

**170 ties, 71 people, 158 companies, 71 dossiers brought from zero**, and
**76 of the 170 carry a year** — a rate no other genre approaches, because the
compiler dates a seat when he is writing a career.

**Precision 19 of 20** on a random sample checked against source context, which
is the band §4c–4g occupy. The one questionable row sits under a death notice
listing the subject's family; the kinship guard did not fire because the notice
uses `enfants` and `petits-enfants` across a rule separator.

Merged as `source_genre = "person_dossier"`, excluded by
`build_network.py --no-person-dossier`.

## 4m. What the unread documents are, and why that had to be measured

§4l exists because a claim in this document was wrong. The Tunisian residue was
written off as books and honours lists; it was not, and following it up found a
genre. That is a warning about the *method* of the claim, not about Tunisia:
**"the rest is unreadable" is an assertion, and this repository states
assertions with a file behind them.**

`src/audit_coverage.py` (stage 23) is that file. It reads every document with
usable text that yields no tie — 2,129 of them — and files each under the
**register** it is written in, meaning the shape a parser would have to
recognise. It adds no ties and touches no network output.

| Register | Documents | Characters | What it is |
|---|---|---|---|
| `press` | 1,151 (54.1%) | 22.2 M | Newspaper cuttings: arrival notices, tender results, election counts |
| `no_signal` | 292 (13.7%) | 4.9 M | Nothing matched |
| `person_career` | 282 (13.2%) | 30.1 M | The person-anchored register of §4l |
| `deed` | 170 (8.0%) | 3.0 M | Notarial: `Aux termes d'un acte reçu par Me Bérenger, notaire à Saïgon` |
| `apposition` | 127 (6.0%) | 7.3 M | `M. Honoré Dejean, directeur de la Société agricole de My-Duc` |
| `certificate` | 77 (3.6%) | 1.3 M | The caption under a reproduced share certificate |
| `board_list` | 30 (1.4%) | 1.6 M | **A board heading in a document the parser read as empty** |

These are the counts *after* the two fixes below, which the audit itself
prompted: three of the `board_list` documents now speak and are no longer in
the table.

Registers are tested in order and the first match files the document, so a
board list inside a press compilation counts as a board list; every register's
match count is kept, so the file can be re-sorted on any of them.

### The finding is a negative one, and it is the useful kind

**Indochina is 60% of the silent set** — 1,282 documents holding 48.2 M
characters, 68% of all unread text in the corpus, at 47.4% coverage against
the corpus's 63.7%. It looked like the Tunisian case at twenty times the
scale, and 826 of its 1,011 silent *company* dossiers carry `MM.` name lists —
19,933 of them.

They are not boards. `MM.` is French for *Messrs*, and in these documents it
introduces the bidders at an abattoir tender, the count in a chamber-of-commerce
election, and the three veterinary inspectors on the jury of a cattle show. A
parser that read `MM.` lists as board lists would manufacture thousands of
false ties out of a livestock competition. The Indochina residue is a
compilation of newspaper cuttings, deeds and council minutes — a different kind
of document, not an unread board list.

That is worth having measured in both directions. It says where not to spend
effort, and the two small rows say where a little still pays.

### Two defects the audit found

**`LINE_MEMBER_RE` read only half of its own register.** The §4g line register
was written for `ASSIS (Henri), à Oran ;` — a comma after the parenthetical.
The same annuaire also prints

```
REY (Antonio)\x00; président\x00;
MESSA (Silvio)\x00; adm. délégué\x00;
```

with a **semicolon**, and with whatever the extractor emitted for a thin space
sitting in the gap — a NUL, which `\s` does not match. Both had to be fixed
together: allowing the semicolon alone still matched nothing. Corpus-wide the
fix adds 104 member lines and brings three silent documents to speech. Small,
but the register was being read at half its reach, and NUL characters occur in
**8.4% of the corpus and 13.3% of the silent set** — over-represented exactly
where extraction fails.

**§4l refused men whose surname begins with an article.** `looks_like_org` was
applied to the catalogue form, `Le Gac de Lansalut (Charles)`, where the
leading *Le* reads as a company name. It is now applied to the reordered form,
`Charles Le Gac de Lansalut`, which it passes — while `Georges Taupin & Cie`,
a partnership, is still refused. Stage 3j went from 150 ties to 170.

A hypothesis that did **not** survive testing is worth recording too: the NUL
characters looked like the single cause, since `parse_ties` uses `\x00` as its
own internal sentinel for protecting annotations, and a source NUL colliding
with it is a real hazard. Stripping control characters at load recovered
nothing on its own. The separator class was the cause; the NUL was only half
of the gap.

## 5. Dating and attributing ties

A document is split at **anchors** — points that fix a date, a source, or a
company. Text between one anchor and the next inherits that anchor's
attributes. Anchors are dated press citations, inline directory entries
(`AEC 1922-519 —`, `Annuaire Desfossés, 1945`), numbered directory entries,
*Annuaire industriel* notice heads, capitalised headings, and the "local
companies" register. Board lists inside a segment are then found by explicit
list markers and parsed into person/role pairs.

Two anchors can match the same position, so each has a precedence: a dated
source beats an undated entry head, and a genre-specific entry pattern beats
the generic capitals one. Without it the weaker name won and a zero-length
segment was inserted between them.

Four failure modes were found by inspecting output rather than code, and each
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

**An unread entry head, and the mega-board it builds.** Some firm-years held
40 to 90 directors. The methodology used to guess that these were constitution
or subscriber lists — a plausible reading, and wrong. Reading the source for
the worst case, *Compagnie du Port de Fedhala* with 83 directors in 1921,
showed a dossier that reprints the AEC 1922 entries for a dozen *other* firms
under a heading the compiler wrote as `ET UNE KYRIELLE DE SOCIÉTÉS…`. None of
those entry heads matched an anchor, so a cork factory's board, a metalwork
shop's board and ten more all landed on the port company. The same shape
explains the *Annuaire industriel* cases, for a different reason: that
publication alphabetises each notice on a keyword and puts the rest of the
legal name in parentheses —

```
ALLUMETTES (Soc. indo-chinoise forestière et des), 41, bd de Magenta, Paris…
BANQUE de l'INDOCHINE, 96, bd Haussmann, Paris, 8e…
FORGES, ATELIERS et CHANTIERS d'INDOCHINE, Bureau : 119, bd Haussmann…
```

— and the anchor for it required the parenthetical, so the second notice never
anchored and the Banque de l'Indochine's board was credited to a match factory.
Three separate reading errors had to be fixed together: the parenthetical is
optional; particles chain, so `de l'` is one link and not two; and the keyword
itself may contain commas, so cutting at the first one named the third firm
*Forges*. The name is then rebuilt by inversion — parenthetical first, keyword
second — which recovers *Société indo-chinoise forestière et des allumettes*
and, for 42% of heads, a firm already in the dataset. Casing is left as the
annuaire printed it, because lowering `COTONNIÈRE de TOLGA` correctly needs to
know that one word is a descriptor and the other a place, and `org_key` folds
case anyway.

Two smaller reading errors in the same family: the AEC page reference is
written three ways (`AEC 1922-519 —`, `AEC 1922. — 489 —`, `AEC 1922. 495 —`)
and only the first was matched; and once a listing is running the compiler
drops the prefix and prints the page alone (`509 — Sté des briqueteries de
Fedhala`). The bare-page form needs a guard, because short numbers are
enumerated clauses in legal prose — *"3 — Modifications diverses aux articles
4, 8, 12"*. Requiring three digits, which every real reference has since the
annuaire runs to 800–1,200 pages, took a hand-checked sample from 44 matches at
roughly 60% precision to 19 at 19 of 19.

The largest firm-year the dossier parser produces falls from 83 directors to
52, and the ceiling in `checks.py` from 200 to 90. One firm-year in the
*merged* network still reaches 82, and it has a different cause worth stating
rather than smoothing: the annuaire's own numbered key sometimes gives one
entry to several firms at once, joined with a plus sign —
`Houillères du bassin de la Loire + Houillères des Cévennes… du Dauphiné`.
Those 82 people are the boards of three nationalised coal undertakings pooled
into one pseudo-firm. **22 companies have such a combined name, carrying 185
of 94,189 two-mode edges (0.20%).** They are left as the source wrote them:
splitting a name on a plus sign would also cut the ones where it separates a
firm from its depot rather than from another firm, and the affected share is
too small to justify guessing. Filter on a `+` in `name` to drop them.

The lesson is the one this section keeps repeating: an implausible number is a
parsing report before it is a historical finding, and the cheapest way to tell
them apart is to read the source.

**A role label read as a person.** 1,514 parsed members contained a colon —
`Adm.: MM. Henri Girche`, `Direct.: M. Patrick O'Quin`, `Imp.: sucre`. Every
hand-checked one was a swallowed directory field label, but they split in two:
most hide a real name behind the label, and some are a field *value* and no
person at all. Discarding all 1,514 would have thrown away real ties, so the
label is stripped and the name kept; a colon surviving the strip means a label
this rule does not know, and no name in the corpus contains one, so the row is
rejected. `checks.py` asserts that no member name carries a colon, and that
`Ed. Bousquet` and `A. R. Fontaine` pass through untouched.

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

## 5c. Coding positionality in the colonial order

`code_positionality.py` codes each person `colonial` or `native`, with
`intermediate` and `local_non_french_elite` for the two groups the binary
cannot hold. The evidence is the name as printed plus the territory the
person's ties were observed in — onomastic inference and nothing else.

**Every obvious rule is wrong.** Each was measured against all 34,447 names
and rejected:

| Rule | Hits | Why it fails |
|---|---|---|
| Vietnamese surname `Le` | 124 | All French: *Le Bret*, *Le Play*, *Le Trocquer*. |
| Vietnamese particle `Van` | 163 | All Dutch: *Van Nierop*, *Van Brée*. |
| Malagasy prefix `Ra-` | 51 | All French: *Rastoin*, *Rabeau*, every *Raymond* and *Raoul*. |
| `Bey` / `Pacha` as indigeneity | ~60 | A rank granted to Europeans in Egyptian service: *Boinet Bey*, *H. Naus bey*. |
| Short-syllable triples as Chinese | 91 | Caught *Max Katz*, *Louis Bovet*, *Paul Blanc*. |

The surviving rules require a conjunction — an indigenous-name pattern *and* a
plausible territory — and for Vietnamese a full name structure rather than one
token. Even the Malagasy prefix needed a 4-character stem before *Rabeau*
stopped matching, a false positive caught by the check suite rather than by
reading the code.

**The quality gate was itself biased.** Rows where the parser captured leading
prose were excluded, and indigenous names turned out to be over-represented
among them: the honorific register (*S. Exc. Hadj Thami Glaoui*, the Pasha of
Marrakech) and the directory lines listing Moroccan and Jewish merchants
(*œufs. Meknès. David A. Benchimol*) both attract leading matter. Excluding
them understated an already tiny figure and discarded the best-documented
figures, Blaise Diagne among them. A recovery pass now strips leading matter
before the gate, raising the Maghrebi count from 81 to 89, Vietnamese from 34
to 39, and Senegal from zero native board members to two.

**What the variable will and will not carry.** It supports aggregate
composition — "board members with an indigenous name are 1.0% in Morocco and
0.0% in French Equatorial Africa". It does not establish any individual's
origin, and `colonial` in particular is inference from absence, not positive
evidence: it means only that no indigenous marker was found. All 205
non-European codings are written to `positionality_review.csv` precisely
because at that scale hand-checking beats any confidence score.

Two further limits. Recall is unknown: a French-transliterated indigenous name
with no diagnostic marker is coded `colonial` and there is no way to count how
often that happens, so 0.6% is a **lower bound**. And the same-surname
same-initial merging described in §4 applies here too — the Hui-Bon-Hoa family
appears as six nodes, some of which may be one person.

## 5d. Drawing the network

`src/make_figures.py` writes `figures/`. Three decisions there are analytical
rather than cosmetic, and each of them can distort a reading of the data.

**The whole graph is never drawn.** At `weight >= 1` the interlock network is
5,959 firms and 78,530 edges: rendered as a node-link diagram it is a solid
disc that shows only that the ink is dense. Every figure is an explicit
subset, and the subset rule is printed with the figure. Figure 1 raises the
threshold to two shared directors, takes the largest component, and keeps the
170 firms of highest weighted degree — 1,401 interlocks. Reading a *global*
property such as density or centralisation off that picture is a mistake; the
figure is a map of the core, and the numbers for the whole graph are in
`network_stats.csv`.

**Colour is capped at three territories, not eight.** In a bar chart any two
categorical colours are adjacent only along the axis; in a node-link diagram
any two nodes can end up touching, so the palette must survive an all-pairs
separation test rather than an adjacent-pairs one. That caps the categorical
slots at three. Firms are coloured by their first territory, folded to
Indochine, Maroc and Afrique occidentale française — the three largest in the
core — with everything else a recessive grey that is *not* a fourth category
and must not be read as one. The palette is checked with the validator, in
both light and dark surfaces, rather than judged by eye; light-mode aqua sits
below 3:1 on the surface, so the figure ships direct labels on the largest
nodes and a full table view rather than relying on the hue alone.

**Small multiples share one layout, computed once.** Figure 2 draws one panel
per period. The obvious implementation — lay out and normalise each period's
subgraph independently — rescales every panel to fill its box, which made the
1914–1929 panel (2,943 interlocks) look *smaller* than pre-1914 (479): the
visual encoding then contradicts the data. The layout is instead computed
once on the union of all periods and each panel draws its own edges at those
fixed coordinates, with one size scale throughout. A firm therefore sits in
the same place in every panel and the panels are directly comparable. The
normalisation also fits to a central percentile band rather than the extremes,
because a spring layout throws one or two nodes far out and scaling to the
true min/max squashes everything else into a dot; the outliers are clamped to
the frame, which is why a panel occasionally shows a node pinned at a corner.

An empty region of a period panel means no *recorded* shared directorship
then, which is a statement about the collection and not about the firms — the
same caveat as §6, and the reason the panels carry their tie counts as text.
Layouts use a fixed seed, so the figures are reproducible; a spring layout has
no meaningful axes and distance between unconnected nodes carries no
information.

### The whole graph and the territories

`src/make_territory_figures.py` writes the complementary set: figure 4 (every
firm), figure 5 (the territory matrix) and one figure per territory. Where
stage 7 subsets deliberately, these do not — which raises different problems.

**Figure 4 draws all 5,959 firms and 78,530 interlocks.** At that density a
node-link diagram cannot be read firm by firm, and it is not offered for that.
The question it answers is compositional: are the empire's boards one
integrated elite or separate territorial ones? Colour is the firm's first
territory folded to the three largest, and the answer the figure gives is
"both" — Indochine, Maroc and AOF each hold a visibly distinct lobe, joined
through a dense mixed core. Node radii are 42% of the core figure's and edge
ink 42% of its opacity, because the settings tuned for 170 nodes render 3,550
as a solid disc.

**Nothing is dropped to make the picture tidy.** 98.5% of the firms sit in one
giant component; the other 46 are in 22 tiny ones that a spring layout flings
into the corners. They are packed into a strip below a rule, labelled as
unconnected, rather than being silently cut — a figure captioned "every firm"
has to contain every firm. `checks.py` asserts the drawn node set equals the
graph's, for figure 4 and for each of the 42 territory figures, so the claim
is enforced rather than merely intended.

**Figure 5 is a matrix, not a node-link diagram.** Aggregated to territories
the graph is small (54 nodes) and nearly complete (863 of 1,431 possible pairs
share at least one director), which is exactly the regime where a node-link
diagram degenerates into a scribble and a matrix becomes readable. The cell is
the count of directors holding board seats in both territories; rows and
columns are ordered by size, which is what makes the core-periphery structure
legible. Two things to know before reading it: the shading steps by **rank,
not linearly**, because the counts are heavily skewed and a linear ramp would
put everything but the top two pairs — Maroc–Indochine at 4,477 shared
directors and Maroc–Algérie at 4,439 — in the palest step; and a firm listed in two territories contributes its whole board to
both, which is the tie being counted rather than an artefact — a
Paris-registered firm operating in Morocco and Indochina genuinely links them.

**Per-territory figures are that territory's complete graph**, from its own
bundle, with no threshold and no top-N. They use one hue and so carry no
legend, the heading naming the series. The giant component is laid out alone
and scaled to fill the canvas, with the residue in the same bottom strip: a
joint layout let three stragglers shrink Senegal's 39-firm main component to a
quarter of the frame. Twelve territories get no figure because no two of their
firms share a director — recorded and listed on the page rather than omitted,
since that is a fact about the collection's coverage, not about the territory.

## 5e. Betweenness, and what it is measuring here

`src/centrality.py` writes `company_centrality.csv`. Degree counts how many
firms a firm shares directors with. Betweenness counts how often it lies on
the shortest path between two firms that share no director of their own — so
it picks out **brokers** rather than hubs, and a firm with a modest board can
score highly if it is the only thing joining two blocs. Figure 6 draws it on
figure 1's node set and layout, so the two can be read against each other.

Three decisions determine the numbers.

**Computed on the whole graph, displayed on a slice.** Betweenness is a global
property: the shortest paths that matter run through firms outside any core
one might draw. It is computed on the giant component of the interlock graph
at `weight >= 1` (5,871 firms, 78,530 ties) and then displayed on whatever
subset a figure shows. Recomputing it on the 170 drawn firms would yield a
different quantity wearing the same name, and would systematically flatter
firms that happen to sit in the middle of that particular selection.

**Exact, not sampled.** `networkx` will estimate betweenness from *k* pivot
nodes in a few seconds; the exact Brandes computation takes about a minute at
this size, which is affordable. Nothing in the file is an estimate, so no
sampling error needs reporting.

**Unweighted.** Edge weight in this graph is the number of shared directors —
a measure of tie *strength*. Shortest-path algorithms read weights as
*distances*, so passing the weight through unchanged would make the most
heavily interlocked pairs of firms count as the furthest apart, exactly
inverting the intended meaning. Inverting the weight (`1/w`) is defensible and
would give a different, also-defensible ranking; the binary graph is the
standard treatment in the interlocking-directorate literature and is what is
used here. Anyone wanting the weighted variant has the edge list.

**The caveats from §6 carry over, and one is sharpened.** Betweenness is more
sensitive to missing data than degree is: a single unobserved tie can reroute
many shortest paths, so a firm's score depends on ties this collection happens
to record. It also inherits the entity-resolution limits of §4 — an unmerged
duplicate splits a firm's brokerage across two nodes, and a wrongly merged
surname invents brokerage that no one exercised. Read the ranking as a
description of this network, not of the colonial economy.

## 5f. Placing firms below the level of the colony

The source files a firm under a territory. That unit hides two things worth
seeing: that Saigon and Hanoi were substantially separate business worlds
inside one *Indochine*, and that a large share of "colonial" firms were run
from Paris. `src/geocode.py` recovers the city; `make_geo_figure.py` draws the
interlock network over it, with position meaning location rather than
connection.

**Two fields, in order of trust.** `place_listed` comes from the catalogue
title and is a clean city name (1,581 firms). `head_office_observed` is
transcribed prose — *"Paris, 1, rue de Stockholm. Tél. : LAB. 18-34"* — and
covers 1,589. The first is preferred; the second is parsed only where the
first is absent, and `source_field` records which was used so the weaker half
can be dropped.

**Why a prefix is parsed rather than the whole string.** A head-office line is
`<city>, <street address>`, and Paris street names include *rue de Rome*, *rue
de Constantinople* and *rue d'Alger*. Searching the full string for city names
would relocate Paris firms to Italy, Turkey and Algeria — a bug that would
look like a finding. The string is cut at the first digit or street word and
only the prefix is matched, which is also why *"le siège social est à Paris"*
resolves correctly. `checks.py` asserts all four of those cases.

**The gazetteer is curated, not geocoded.** `data/reference/places_geo.csv`
holds 176 cities with coordinates, territory and variant spellings. It is
hand-built because the names are historical — Bône not Annaba, Tourane not Da
Nang, Fedhala not Mohammedia — and no modern geocoding service returns them
reliably. It is an input: editing it changes the output.

**Coverage: 3,170 of 10,373 firms (30%), and 2,009 of the 5,959 in the
interlock graph (33%).** The map draws those. It is not a map of the empire's
firms but of the ones whose address survived, and the unplaced 67% are absent
rather than assumed.

**Three readings the figure would otherwise invite, and why they are wrong.**
A head office is not an operation: a rubber plantation in Cochinchina run from
a Paris office appears at Paris, which is a true fact about control and a
false one about production. A city's size on the map is firms *recorded* there,
inheriting all of §6's coverage unevenness. And ties within a single city
cannot be drawn — an edge from Paris to Paris is a dot — so the 5,146
within-city interlocks appear as a table column rather than on the map, against
1,100 drawn city pairs; a reader who counts only the lines undercounts the
network badly.

The headline result survives all three: 37% of placed firms in the interlock
graph were run from Paris, more than the next eleven cities combined (Alger
147, Saïgon 135, Casablanca 127, Hanoï 56, Tunis 52 against Paris's 732), and
the heaviest lines radiate from Paris rather than running between colonies.

## 5g. The descriptive figures

Every figure this collection had was a network — node-link diagrams, a
territory matrix, a map. Topology is what the dataset is *for*, and it is not
what a reader needs first. Four of the caveats in this document are load-bearing
and lived only in prose:

- one year holds a fifth of all dated observations;
- the person index is confined to a single period;
- most interlock edges rest on one shared director;
- four territories hold most of the ties.

A caveat in prose is a caveat readers skip. `make_descriptive_figures.py` draws
ten figures whose whole job is to make those four visible, plus six more on
composition and concentration. `figures/descriptive.html` carries all ten with
a table of numbers under each.

**Where the form came from.** Each figure's job picks its form: a distribution
gets columns, a ranked magnitude gets horizontal bars, a composition within
ordered groups gets a 100% stack. One figure changed form during construction
and the reason is worth recording. "Which firms are brokers rather than hubs"
started as a degree-rank against betweenness-rank scatter. Plotted honestly —
both axes on one shared scale, since distance from the agreement line is the
entire claim and only means something if a unit on one axis is a unit on the
other — the top 400 firms by betweenness occupy a thin band across the top and
nine tenths of the canvas is empty. The question is a ranked comparison of one
derived quantity, so it became a ranked bar of `broker_gap`.

**Colour.** The palette is `make_figures.py`'s, extended from three categorical
slots to five for the genre figures, taking slots 4 and 5 from the reference
palette in its documented order rather than inventing hexes. Five slots pass
every hard gate on the *adjacent* pairlist — which is what a stacked bar uses —
at worst CVD ΔE 9.1 light and 8.4 dark against a floor of 8. The three-slot cap
still binds on the all-pairs forms, the node-link diagrams and the map, and
`checks.py` enforces that split: the two extra hues may appear on a rect and on
no circle. Three light-mode slots sit below 3:1 on the light surface, so the
relief rule applies and is not optional: every figure carries direct value
labels, and every figure ships a table view, which `checks.py` also asserts.

**One figure reports a defect rather than hiding it.** Among the top brokers is
"Agence centrale à PARIS", which is not a firm but a mis-cut field label. It is
left in place and named in the caption: a junk node holding a real structural
position is exactly the company-name hygiene debt the codebook flags, and
silently filtering it would hide the evidence for a limitation this dataset
states elsewhere in prose.

## 5h. The structural figures

§5g describes the observations; this describes the graph they build. Both come
before any substantive result, and for the same reason: a reader about to
compute a centrality, a community or a distance needs four facts first, and
none of them was anywhere in the repository.

**One component, held by single ties.** 98.5% of the 5,959 firms sit in one
component — and 47.4% do once an edge needs two shared directors rather than
one (`fig21`). The connectedness the network figures show is therefore
substantially the connectedness of the weakest possible evidence. Every
component, distance or centrality result computed here has to name its
threshold, and `fig22`'s mean path length of 3.23 is the one-shared-director
graph's number, not a property that survives filtering.

**A core that is one man.** The k-core decomposition (`fig19`) does not decay
smoothly. Two shells — k = 46 with 35 firms and k = 71 with 72 — have induced
density **1.000**: they are complete graphs, and no board structure produces
one. `fig26` takes the deeper one apart. All 2,556 of its edges carry
`homberg-o`, who is recorded on all 72 boards; without him 532 remain and the
core falls to k = 13. Octave Homberg did chair a financial group of roughly
that size, so this is not established as a parsing error. It is established as
a robustness fact: the network's deepest structure rests on one identifier, and
one entity-resolution failure on that name would erase it. `checks.py` asserts
both the density and the sole-holder claim, so neither caption can drift from
the data.

**Clusters that are not colonies.** Louvain at seed 7 finds 65 communities at
modularity 0.48 — a real partition — but no large community is territorially
pure (`fig23`, most homogeneous 70%), and no block stands apart from the others
(`fig20`). Consistently with that, **67.5% of interlock edges join two firms
filed under different territories** (`fig24`). The cross-border share falls
monotonically from 73.8% before 1914 to 46.4% after 1962; the source mix
changes over the same span (§5g, `fig9`), so that decline is real in the data
without being established as a historical trend.

**Not a scale-free network.** The degree CCDF (`fig18`) bends downward on
log–log axes rather than running straight, in both the full and the weight ≥ 2
graph. There is a characteristic scale, so a fitted power-law exponent would be
describing the annuaire as much as the empire.

**Form and colour.** Eight of the ten are charts and two are drawings. That
split is the point rather than an accident: "is this graph one lump or several"
is a number, and a node-link diagram is not an answer to a number. The two that
are drawn are drawn because their claim is about adjacency — which clusters
touch, and what is left of a clique when one vertex is removed. `fig26` uses a
circular layout precisely because a complete graph has no layout worth
computing, and a circle keeps every node at a fixed point across both panels so
the edge set is the only thing that differs. `fig20` sizes its nodes as
`r ∝ √firms` rather than through the shared `radius()` helper, whose square
root is taken after rescaling to the drawn set — over a 191–611 range that
turns a 3.2× difference into a 20× difference in area, and the caption says
"area is the firm count". Colour stays inside the same cap as everywhere else:
three slots plus grey on the node-link forms, five on the stack, two on the
CCDF — that pair passing every gate including contrast, at CVD ΔE 24.7.

**One primitive fix, with a visible consequence.** The shared `columns()` helper
floored every bar at one pixel. On a log axis that is wrong: a count of zero is
not a short bar, it is no bar, and the stub read as "one". Fixing it removed 38
phantom bars from `fig11`, which had been drawing a continuous run of board
sizes up to 82 where most of the tail is empty, and it is what makes the empty
levels between k = 46 and k = 71 visible in `fig19` at all.

**Reproducibility.** Stage 12 adds three more set-shaped hazards of the kind
§5d describes: `connected_components` yields sets, `core_number` returns a dict
keyed by node, and `louvain_communities` returns a list of sets. Each is sorted
into a total order before anything downstream reads it, and the path-length
sample draws from a sorted list with an explicit seeded RNG rather than from
the component's set. `checks.py` runs the partition under two values of
`PYTHONHASHSEED` and requires the same answer.

## 5i. Drawing at the level of the node

§5d draws the network at the scale of the whole and says why: at 3,000 nodes
and 39,000 edges the unit of reading is the shape, labels go in the margin on
leader lines, and an edge is one of thirty-nine thousand. That is the right
treatment for the question those figures answer. It answers no question of the
form *which firms, exactly*.

Stage 13 draws six graphs small enough that the unit of reading is the
individual node. The primitives are in `draw.py` and differ from
`make_figures.draw_network` in four ways, each following from that change of
scale.

**Curved edges.** Straight segments between scattered nodes make a moiré of
near-parallel lines in which every crossing looks like a node. A quadratic
bezier with a consistent bow separates edges that share an endpoint. The bow is
computed after sorting the two endpoints, so it does not depend on which way
round the pair happened to be stored.

**Labels on the node, with a halo.** `paint-order="stroke"` paints a
surface-coloured stroke first and the fill on top, which gives each glyph a 3px
moat and makes a label legible over the edges it covers. Without it, in-place
labelling is not available at all and the labels have to go in the margin with
leaders. Placement is a greedy pass over the nodes in importance order, trying
eight offsets around each; a node whose label fits nowhere is **skipped rather
than drawn overlapping**, and the table view carries every name regardless.

**Layouts that put a variable on the canvas.** A spring layout means
"connected things are near each other" and nothing else. `fig29` places a firm
on the ring for its core number, so radius is a measured quantity; `fig30`
orders firms along an axis by territory, which is the variable the figure is
about and the one a force layout would destroy; `fig31` uses two columns
because a bipartite graph laid out by force hides the thing that makes it
bipartite. `fig31`'s two columns are then ordered by the barycentre heuristic
to cut crossings — that the Indochina firms end up together and the Moroccan
ones together is an *output* of that ordering, not a grouping imposed on it.

**Edges that can carry a category, under the same cap as everything else.**
The first version of `fig28` painted its cross-territory edges in categorical
slot 2 — the same orange as the Algeria nodes beside them, so one colour meant
two different things in one figure. The hues are spent on territory there, so
the cross/within distinction became a step along the *mark* grey ramp plus a
width increase, and the hue treatment moved to `fig30`, where nothing else
competes for it. `checks.py` now polices strokes as well as fills, which is what
caught the second half of that mistake: the darker grey was taken from the
*text* ramp, and text tokens are for ink a reader reads, not ink a reader
measures.

**Two checks were wrong before they were right.** The clipping check handled a
`transform` only for the -90° case, so it measured `fig30`'s 60° firm names
against the wrong canvas edge entirely; it now projects a rotated label's width
onto both axes. And the arc diagram was not reproducible: `G.subgraph` returns
a *view* that iterates a set, so under a different `PYTHONHASHSEED` the arcs
landed in the same places but their path segments were emitted in a different
order and the committed SVG changed on a re-run of unchanged data. This is the
same hazard §5d describes, in a place the existing guard did not reach;
`ordered_subgraph` fixes it and `checks.py` now probes for it.

## 5j. The legislative layer, and three kinds of continuity

`src/make_legislative_layer.py` joins the two mandate readings (§4i, §4j) to
each other and to the company network, and writes three files: `legislators.csv`
(one row per parliamentarian), `edges_legislator_interlock.csv` (two
parliamentarians, one board), and `legislative_continuity.csv` (the roster
snapshots as transitions). `src/make_legislative_figures.py` draws figs 34–39.

**1,448 parliamentarians are named in the corpus; 574 of them sat on a colonial
company board; 111 sat in both chambers.** Those are the headline numbers, and
the second is the one to be careful with — see below.

The word "continuity" hides three different measurements, and conflating them
is the easy mistake here:

1. **Continuity of tenure** — one man's own run, `first_year` to `last_year`.
   fig34 draws it.
2. **Continuity of presence** — whether the *same* man is in the compiler's next
   directory. This is what `legislative_continuity.csv` measures, as
   entered/stayed/left between consecutive snapshots, because a roster is a
   census and the interesting number is the turnover between two of them. fig35
   draws it, and the result is stark: carryover runs **0.471 → 0.794 → 0.568**
   across 1930, 1932 and 1936, and then **0.009** into 1954. Two of 232 men
   cross that gap. A war and a republic fall inside it.
3. **Continuity of position** — whether a *board* keeps a parliamentarian across
   snapshots, which is the firm's access rather than any career. fig37 ranks the
   boards but deliberately does not separate continuous access from rapid
   succession, and says so.

A firm can hold parliamentary access continuously for thirty years while never
keeping the same parliamentarian for two consecutive volumes. The reverse also
happens. Neither is visible in a single number.

**Two men on one board may never have met.** An interlock edge here carries
`mandates_overlap`: `1` where the two known terms intersect, `0` where they do
not, and *empty* where at least one term is unknown — which is **277 of 404
pairs**. That column is stated rather than filled: an analysis that reads every
shared board as a live connection overstates the network, and one that demands
a proven overlap understates it by the size of the unknown column. The figure
caption carries both numbers for the same reason.

**`key_ambiguous`, and why a headline number needs it.** A person key with no
forename attested is a surname bucket rather than a man. Joining `paris` to a
34,500-person network returned 34 companies belonging to several different
people, and the node was the largest in the first draft of fig36. The mandate is
still real — the corpus does name a senator by surname alone — so the row stays
and is flagged, and every company-side figure and the interlock graph drop it.
That is why the interlock count is 404 rather than the 831 an unfiltered join
gives, and the 574 "on a colonial board" should be read as an upper bound whose
ambiguous share is in the column.

**Two figure decisions worth stating.** No sankey, no bump chart, no chord
diagram: all three encode flow between ordered categories, and what the
snapshots record is presence in a census whose gaps are as often the compiler's
silence as a man's departure. A ribbon between 1936 and 1954 would assert a
continuous quantity across an eighteen-year hole. The presence grid states what
is known — present, absent — and lets the reader see the break. And fig34 drops
any span longer than 55 years along with every surname-only key, because the
first draft gave René Hachette a 78-year term: no one sat that long, so a bar
saying so is two men.

## 5k. Coding companies by political connection

`src/code_political_connections.py` (stage 16) turns the person-level office
evidence into a company-level variable, and
`data/reference/political_connection_rules.md` is the argument for it — the
definition, the tier ordering, the offices considered and rejected, and the
four things the coding cannot do. **Read that file before using the variable.**
This section records what came out and the three design decisions a reviewer
would challenge first.

A firm is coded connected when someone holding a board seat in it is attested
holding an office of state. That is the standard definition in the
political-economy literature — Faccio's is a member of parliament, a minister
or a head of state, or a close relation of one — with the extension the setting
requires: the colonial executive counts, for the reason given in §4k.

Of **6,454 firms with at least one observed board seat, 2,243 (34.8%) are
connected**:

| Tier | | Firms | Share |
|---|---|---|---|
| 4 | `executive` — minister, head of state, colonial governor | 884 | 13.7% |
| 3 | `legislature` — deputy, senator | 713 | 11.0% |
| 2 | `administration` — colonial administrator, conseiller d'État, prefect, consul | 501 | 7.8% |
| 1 | `local_or_proxy` — municipal office only, or through a relative | 145 | 2.2% |
| 0 | `none` | 4,211 | 65.2% |

**The tier ordering is an assumption, not a finding.** Ranking a minister above
a deputy follows Faccio. Ranking a governor-general *with* a minister rather
than below him is a judgement specific to the colonial setting. Both are argued
in the rules file, and the six `has_*` flags and six `n_*` counts are all in
the output, so the tier is reproducible from them in one line and replaceable
in one more.

**Sitting against former is the finding.** The two are never summed, and the
split runs opposite ways in the two top tiers:

| Tier | firms with a *sitting* holder | with a *former* one |
|---|---|---|
| `executive` | 859 | **473** |
| `legislature` | 713 | **35** |
| `administration` | 452 | 115 |

Ministers and governors join boards *after* leaving office; deputies sit on
boards *while* serving. That is two different mechanisms — a revolving door and
a live conflict of interest — and a single "politically connected" dummy would
average them into one meaningless number. Because `former` is read from the
compiler's own `ancien` / `honoraire`, which he omits far more often than he
omits an office, `n_former` is a floor and `n_sitting` a ceiling.

**Concurrency is reported with its denominator, or not at all.** A tie observed
in 1950 and a mandate held 1919–1932 are both attached to the firm, and the
base coding does not require them to overlap. Where both the tie year and the
office span are known, `n_concurrent` counts the director–firm pairs that
actually overlap: **326 of 688 testable pairs, out of 4,212 connected pairs
in total**. Fewer than one pair in five can be tested at all. `n_concurrent`
is therefore not a corrected `n_connected` but a much smaller, much
better-evidenced subset, and `n_testable` sits beside it in the file and in
fig 44 so it cannot be quoted without its denominator.

**Indirect connection is kept out of the tier.** `n_connected_neighbours`
counts the firms sharing a director with this one that are themselves
connected, and `indirect_only` marks the 3,254 firms — most of tier 0 — with a
connected neighbour and no connected director of their own. Folding that into
the tier would let the variable inflate without limit as the network grows, and
one interlock from a minister's board is a different construct from having the
minister on yours.

**Confidence, and why `low` is not droppable.** `high` where the connection
rests on a roster entry or two independent mentions, `medium` on one apposition
or bracket, `low` where the connecting person's key has no forename attested or
the only evidence is a footnote career line. Of the 2,243 connected firms:
**1,052 high, 349 medium, 842 low**. `low` is 38% of the connected set, not a
residue. Report what happens to your result when you exclude it.

Two limits carried over from elsewhere in this document and worth repeating
here, because this variable invites both mistakes. It **cannot be read as a
rate** across territories: coverage is uneven (§6), and a territory the
compiler read closely looks more connected for reasons that have nothing to do
with its firms. And it **cannot be compared across `source_genre` without
holding it constant**: the roster genre (§4i) exists precisely to record
political connection, so firms with roster evidence are connected at a far
higher rate by construction.

## 5l. Political connection by sector, and why the raw cross-tab misleads

Crossing the connection coding with sector needed two pieces of work before it
could be tabulated at all, and then a third before it could be read.

### The sector field is not an analysable variable as it stands

`companies.csv`'s `sectors` column is the site's own filing vocabulary, taken as
printed: **109 distinct labels**. Three problems, all fixed by
`src/sectors.py` and the reviewable mapping in
`data/reference/sector_groups.csv`:

1. **The modal value is not a sector.** `Documents généraux (par ordre
   chronologique)` covers 5,397 firms — the chronological clipping dump.
   With its variants, **2,949 of the 6,454 firms with a board carry no other
   sector at all**. Every sector figure is therefore computed on **3,505
   firms**, and says so.
2. **The field carries the site's own navigation text.** Among the 109 labels
   are `Alain LÉGER, créateur du site …, a publié`, `Pour une utilisation
   optimale de nos liens, téléchargez nos pdf`, `Messages personnels` and
   `documents`. These are mapped to `not_a_sector` and excluded, not counted.
3. **One sector is spelled up to six ways.** Six labels are mining (`Mines`,
   `Mines et carrières`, `Groupes miniers transcoloniaux`, `Mines et
   métallurgie`, `Mines et placers`, `mines et industries`); six are banking;
   five are agri-food, two of them differing only in case. Tabulating the raw
   labels splits every real sector into fragments and puts none of them at the
   top.

The mapping groups all 109 into **19 sectors plus two residuals**, and the two
residuals are deliberately distinct: `unclassified` is the *source's own*
economic residue (`Divers`, `Industries diverses`), which is information and is
kept; `not_a_sector` has no economic content and is dropped. `sector_of` takes
the first **non-filing** label rather than the first listed, so a firm filed
under `Documents généraux; Mines` is a mining firm. `checks.py` asserts every
label in the data appears in the committed mapping, so a new label cannot
silently become `unmapped`.

### The raw cross-tab is a board-size artefact

Read naively, `political_connections_by_sector.csv` says finance is the most
connected sector (55.7%) and mining second (44.1%). Both have large boards —
median 10 and 7 — and **a board of ten has ten chances to contain a connected
director where a board of two has two.** Metallurgy (median board 2) and health
and education (median 1) sit at the bottom for the same mechanical reason.

The benchmark is the simplest defensible one. Let *p* be the corpus-wide
seat-level rate — connected director-seats over all director-seats. Under a null
where each seat is independently connected with probability *p*, a firm with *k*
directors holds at least one with probability 1 − (1 − *p*)^*k*, and a sector's
expected share is the mean of that over its firms. `excess_share` is observed
minus expected.

**The adjustment reorders the table completely:**

| Sector | firms | observed | expected | excess | median board |
|---|---|---|---|---|---|
| Culture, sport and leisure | **12** | 58.3% | 20.1% | +38.2 | 3 |
| Press, printing and communications | 56 | 44.6% | 20.9% | **+23.8** | 1 |
| Hotels and tourism | 49 | 42.9% | 22.9% | **+20.0** | 2 |
| Health, education and research | 54 | 25.9% | 15.5% | **+10.4** | 1 |
| Transcolonial and diversified groups | 120 | 55.8% | 46.5% | +9.4 | 8 |
| Transport, ports and docks | 305 | 46.9% | 41.2% | +5.7 | 7 |
| Banking, finance and insurance | 576 | 55.7% | 51.9% | **+3.8** | 10 |
| Mining and quarrying | 555 | 44.1% | 42.6% | **+1.6** | 7 |
| Food processing, livestock and fishing | 461 | 41.6% | 42.3% | −0.6 | 7 |
| Metallurgy and engineering | 28 | 21.4% | 26.1% | −4.7 | 2 |
| Construction and building materials | 148 | 39.2% | 44.3% | **−5.1** | 7 |

Finance and mining, the two sectors the raw shares put on top, are within a few
points of what their board sizes already predict. The sectors genuinely
connected beyond board size are **press and printing, and hotels and tourism**
— both with median boards of one or two, where a single connected director is
the whole board. Culture and leisure scores higher than either, on **twelve
firms**, which is the row to read as noise rather than as the finding. Construction is the one sector materially *less* connected than
its boards predict.

Three cautions on that table. The three sectors at the top have **50–57 firms**
each, so their excess is volatile in a way the 557-firm finance row is not; the
figures print every denominator for this reason. The null **treats seats as
exchangeable**, which they are not, and ignores correlation among a firm's
directors — it is a yardstick for reading the raw shares, not a model. And the
`not_a_sector` residue is *less* connected (21.4%) than the sectored firms,
which is most likely an evidence artefact: a firm known only from a press
clipping offers less text in which an office could be observed.

### The figures

`fig45` is the cross-tabulation proper — sector × tier as a heatmap, rows
summing to 100%, with the sequential ramp applied **within each row** because
one ramp across the table would be dominated by the `none` tier. `fig46` is the
board-size adjustment, observed against expected, ordered by excess.

## 5m. Which sector is central, and six answers that disagree

`src/code_sector_centrality.py` (stage 18) exists because the question "which
sector is most central to the empire network?" has at least six defensible
operationalisations and they do not rank the sectors the same way. The file
carries all six as columns so that a claim can name the one it rests on, and
the figures cite the file rather than recomputing.

The graph is the firm-level interlock projection: 6,011 firms, 79,636 edges,
a giant component holding **98.6%** of the nodes and a mean shortest path of
**3.27** between them. Sectors come from the 19-group mapping of §5l, and a
group is measured only at 25 firms or more — below that the measures are noise.

### The size confound is the whole problem

A sector with more firms and larger boards has more edges for reasons that
have nothing to do with position. Finance holds **15,980 board seats** against
mining's **9,130**, so any raw count — degree, edge share, summed betweenness —
puts finance first before position is considered at all. Three families of
column exist only to strip that out:

- **Per-seat normalisation.** `deg_per_seat` and `btw_per_seat` divide by board
  seats rather than by firm count. On `deg_per_seat` finance (1.73) falls
  *below* plantations (2.21), textiles (2.70) and press and printing (2.93) —
  the last of which is an artefact of the opposite kind, since 40 firms with a
  mean of 5.9 seats each will show a high ratio on very little evidence.
- **A size-matched removal null.** Delete the sector's firms, then delete the
  same *number* of firms drawn at random, 60 times (`--sims` raises it), and
  report the loss as a z-score. This is the column that separates finance from
  mining, which at 553 and 520 firms are within 6% of the same size and so
  cannot be separated by any count: **finance z = +3.35 (p = 0.000), mining
  z = −0.11 (p = 0.58)**. Removing finance costs the giant component more than removing
  an equally large random slice; removing mining costs exactly what its size
  predicts.
- **Path length after removal.** Fragmentation measures nothing here — no
  sector's removal breaks the giant component, which is the substantive
  finding and not a null result. The cost of removal appears as **distance**
  instead: mean path rises from 3.27 to **3.56** without finance (+0.30),
  against +0.09 for mining and +0.02 for food processing. That ordering is
  the finding; the magnitudes move by a few hundredths with every rebuild of
  the graph, and on one earlier build mining's change was negative.

### What the removal test does not license

Deleting a sector from an observed graph is a descriptive operation on this
dataset, not a counterfactual about the empire. It says the network *as
recorded* routes more of its connectivity through finance than through an
equally large random slice of firms. It does not say the colonial economy
would have been less connected without banks: those firms would not have
existed, their directors would have sat elsewhere, and the compiler's coverage
is itself uneven by sector. The same caution applies to `path_change`.

### Hub and broker are different things

`mean_broker_gap` is the mean of `degree_rank − betweenness_rank` across a
sector's firms. Negative means the sector's firms rank better on betweenness
than on degree — they broker more than their connection count would suggest;
positive means the reverse. Utilities (−328.0) and plantations (−262.3) are
the strongest brokers relative to their degree, textiles (+282.5) and health
and education (+247.6) the strongest hubs. Finance is at −121.3, and mining at
−127.0 is beside it: on this measure the two are indistinguishable, which is
why the removal null and not the gap is the column that separates them. Finance
is both hub and broker,
which is why it leads on the raw counts *and* survives the null.

### The figures

`src/make_sector_network_figures.py` (stage 19) draws six, and the first two
answer a different question from the last four. Figures 51 and 52 are asked to
*show* the position — to make finance's centrality visible as geometry rather
than stated as a coefficient — and both place nodes by a measured quantity so
that position is never the output of a force algorithm:

- **fig51** — multi-source BFS shells outward from all finance firms in one
  panel and all mining firms in the other, with each shell drawn as an annulus
  whose **area is proportional to the number of firms in it**. One step from
  finance reaches **70.9%** of the graph; one step from mining reaches
  **56.6%**. An earlier draft placed each shell on a ring *line*, which packed
  3,709 nodes onto one pixel of radius and made the two panels look identical:
  the finding was real and the encoding hid it.
- **fig52** — the 170 core firms with **radius = betweenness rank**, so the
  centre of the picture is the centre of the network. **23 of the core's 40
  most-between firms are finance firms**, and finance's mean rank is 54.4
  against mining's 90.8. The angle is a golden spiral and means nothing; it
  only spreads the nodes apart.
- **fig47** — the sector graph itself: 16 groups, edge weight = interlocks
  between them. Finance–mining alone carries 2,823.
- **fig48** — the interlock core by sector, on the core's own layout.
- **fig49** — the removal test drawn: observed loss against the size-matched
  null. Note the inversion it makes visible — removing finance takes 652 of
  the core's 1,388 edges against 666 for the same number of randomly drawn
  *core* firms, because the core is by
  construction the top 170 by weighted degree, so a random draw inside it is a
  draw of hubs. The null in the CSV is drawn from the whole graph, which is
  the comparison the z-score reports.
- **fig50** — hub against broker, per firm, by sector. The finance firms with
  the highest betweenness have gaps near zero: they are not brokers *instead*
  of hubs.

## 5n. The whole network on the world map

Figure 7 (§5f) already puts the network on the map, but it maps **cities**: it
collapses each city to one node, so 762 Paris firms are a single dot and the
ties *inside* a city are a number in a table rather than lines on the map.
`src/place_on_map.py` (stage 20) and `src/make_world_map_figures.py` (stage 21)
map the **firm**. Doing that means answering, for each of the 6,011 firms in the
interlock graph, "where was it?" — and for a third of them the honest answer is
that the source does not say.

### The placement ladder

Three rungs, and every row of `company_map_positions.csv` records which one it
landed on, because the rungs do not mean the same thing:

| Rung | Firms | What position means |
|---|---|---|
| `city` | 2,028 | An address. `geocode.py` recovered a city from the listed place or the observed head office. A fact about the firm. |
| `territory` | 1,903 | A filing category. No address, but the catalogue files the firm under exactly **one** country, so it sits at that territory's anchor point. A fact about the *catalogue*. |
| `unplaced` | 2,080 | No address and no single country: 1,650 firms with no country at all (most filed only under the transversal *Empire* rubric), 420 filed under several at once, and 9 whose single country — Macedonia, Russia, the Antarctic territories — has no city in the gazetteer. |

That places **3,931 firms (65.4%)** and makes **43,623 of the 79,636 ties
(54.8%)** drawable, against figure 7's 2,028 firms and its between-city ties
only.

**Multi-country firms are deliberately not placed.** `companies.csv` stores
`countries` as a sorted list, so taking the first element — which is what
`territory_of` does for the colour of every other figure — would place a firm
filed under nine territories at whichever sorts first alphabetically. That is a
coin flip dressed as a coordinate, and the firms it would misplace are the
largest and most interlocked in the corpus. They stay off the map with a
`reason` recorded.

Territory anchors are the unweighted mean of that territory's cities in
`data/reference/places_geo.csv`. It is a label anchor, not a centroid of
anything real. The two federations (AOF, AEF) have no city of their own in the
gazetteer and take the mean over their member territories, which are listed in
`FEDERATIONS` in the module.

### What a firm-level map can draw that a city-level one cannot

Firms at one anchor are spread through a disc by a deterministic golden-angle
rule, with the disc's **radius as the square root of the firm count** so its
area is proportional to how many firms are there. Two consequences: the
**9,124 ties that never leave a single place** become short lines inside a disc
instead of a footnote, and blob size is a quantity. Where two places are close
and one is large its disc swallows the other — Brussels, Lyon and Marseille all
fall inside Paris's — so a hairline ring marks each disc's edge and the small
anchors are painted last.

### Paris

**Paris holds 764 of the 3,931 placed firms (19.4%) and touches 19,732 of the
43,623 drawable ties (45.2%).** Figure 54 draws that as two panels on one set
of coordinates: the ties that touch Paris, which are a fan, and the ties that
do not, which are a lattice between colonies.

The three Paris counts are kept apart in `map_geography_baseline.csv`
(`paris_cross_edges`, `paris_within_edges`, `paris_edges_to_unplaced`) because
the first version of that row mixed them. It counted Paris's ties to *unplaced*
firms in the numerator and divided by the drawable total, which put Paris's
reach at 63.7% instead of 45.2%. A ratio whose numerator and denominator come
from different populations is the easiest error to make here and the hardest to
see.

### The geography of a tie, and why colony–colony is a ceiling

Classified by the two endpoints, the drawable ties are 47.1% colony–colony,
36.3% metropole–colony, 11.5% metropole–metropole and 5.0% involving a foreign
country; the median tie that leaves its place spans **3,083 km**. Colony–colony
leading is not a licence to call the network a lattice rather than a hub:
**10,402 of those 20,567 ties stay inside a single territory**, and the firms
involved are disproportionately the ones placed by filing country for want of
an address — exactly the firms that may in truth have been run from Paris. Read
that rank as a ceiling.

### Finance on the map

Figure 56 is where §5m and this section meet. The 388 placeable finance firms
are 9.9% of the placed firms and touch **28.0% of the drawable ties**, and
**41% of them are in Paris**. But finance is *second* on Paris share, behind
the 73-firm transcolonial-groups residual at 44%, and first only among the
sectors with more than a hundred placed firms. The caption computes that
ranking rather than asserting it, because an earlier draft called finance the
most geographically concentrated sector and mining is three points behind it.
What is distinctive about finance is its position in the graph, not its
geography.

## 5o. The basemap, and why the maps had none

Until stage 21 was written the map figures carried their geography on a
graticule alone, on the stated grounds that no basemap shipped with the
repository. That was a constraint inherited from figure 7 rather than a
reasoned one, and it was the wrong call: a world map without coastlines is a
scatter plot wearing a compass, and a reader cannot tell whether a dot at
11°N 43°E is Djibouti or open sea.

`src/fetch_basemap.py` (stage 0b) fetches Natural Earth's `ne_50m_land` once,
simplifies it, and writes `data/reference/world_land.geojson`. The result is
**checked in**, so every later run is offline and every figure draws the same
land. Natural Earth is public domain and is the canonical basemap at this
scale.

**The shapefile is read directly.** `pyshp`, `geopandas` and `fiona` are not
installed and are not worth adding for one layer of polygons: `.shp` is a
documented sequence of little-endian doubles and forty lines read it. The
alternative — trusting a third party's GeoJSON conversion of the same data —
swaps a small amount of code for an unverifiable provenance chain. `checks.py`
tests the reader against a shapefile it builds itself, so the test does not
depend on what Natural Earth happens to ship.

**Land only, and no borders.** The corpus runs from the 1870s to the 1970s, and
a modern border drawn across it would be an anachronism — the whole point of
these figures is that Dakar and Brazzaville were administered from Paris.
Rivers and lakes are omitted too: they carry nothing about the interlock
network and would compete with the edges.

### The bug the simplifier's tolerance had to avoid

Douglas-Peucker at a flat tolerance is what a first pass does, and at 0.12
degrees it **deletes the empire**. Tahiti, Guadeloupe and Saint-Pierre are each
smaller than that tolerance, so the algorithm reduces them to two points and
they disappear, leaving an anchor disc and a label floating on blank ocean. The
tolerance is therefore per ring, `min(0.12, 0.2 * sqrt(area))`: continents are
simplified hard, an island in proportion to itself. Rings below 0.008 square
degrees — about a third of a pixel at these sizes — are dropped instead, 246 of
them. `checks.py` asserts both halves: that a flat tolerance would eat a small
island, and that the per-ring one keeps it.

### The projection is Robinson

Plate carrée, which the first version of figure 7 used, is the projection you
get by not choosing one. It stretches Scandinavia to the width of the Sahara,
and because that figure *derived* its canvas from the latitude span of the
firms that happened to have an address, adding one firm in Reykjavik would have
restretched the whole map and made it incomparable with the firm-level maps.

`basemap.Robinson` fixes the projection and the window for every map in the
repository: latitudes −54 to 70, longitudes uncropped. The latitude window is
the honest crop — the corpus reaches −46 and +61, and drawing Antarctica and
the Canadian Arctic at full height would spend a third of the canvas on ice.
Longitude is never cropped, because the network reaches from Tahiti to
Shanghai.

Two consequences worth stating. Distances are **not** measured on the
projection: `place_on_map.haversine` works on the sphere, so the kilometre
figures in the captions are independent of how the map is drawn. And the
degree labels sit in a fixed column outside the frame rather than on their own
parallel — on Robinson a parallel is shorter than the equator, so a label
pinned to its left end drifts inward as latitude rises and ends up in the
middle of Canada.

### Edges are bowed

Both map stages draw an edge as a quadratic curve bowed to a consistent side,
at 9% of the chord. Straight lines that share a corridor — and on this map
almost every corridor starts in Paris — collapse into one grey smear; bowed,
the bundles separate and the map reads as routes. The bow carries no
information and is stated in the docstring so that nobody reads it as one.

## 5p. The map, split by period

Figure 53 draws every drawable tie at once, which flattens forty years into one
picture. `src/make_period_map_figures.py` (stage 22) splits it on
`build_network.PERIODS` — the same five periods figure 2 uses, so the two are
comparable — into five full-width maps in `figures/by_period/`, a
small-multiple overview (fig57) and the trend that reads them (fig58).

**Every panel is drawn on one set of coordinates.** `gather()` imports stage
21's layout rather than recomputing it, so a firm holds the same pixel in all
five panels and a difference between panels is a difference in the data. In the
small multiples the coordinates are *rescaled*, not relaid out: a Robinson
fitted to the panel width is the full-width one scaled linearly, so the
basemap and the rescaled firm positions agree by construction.

A firm enters a period when it has an interlock **dated** to it.
`edges_company_interlock_by_period.csv` carries 51,818 of the graph's 79,575
edges; the rest are undated and appear in no panel. Firms with no dated tie in
a period stay on the map in grey at a smaller radius — a firm the record has
paused on is not the same as a place with no firms in it, and a blank would
conflate them.

### Paris recedes, and the trend is not an artefact of the placement ladder

Paris's share of the drawable ties falls in every period:

| Period | Drawable ties | Paris share | Paris share, address-only firms | Coverage |
|---|---|---|---|---|
| pre-1914 | 3,322 | 63.5% | **82.6%** | 86.0% |
| 1914–1929 | 11,502 | 51.4% | **65.9%** | 86.4% |
| 1930–1944 | 8,203 | 40.7% | **62.4%** | 84.2% |
| 1945–1962 | 3,969 | 36.9% | **60.2%** | **36.2%** |
| post-1962 | 568 | 26.2% | **42.1%** | 81.3% |

The obvious objection is that the fall is an artefact of the territory rung of
§5n: a firm placed at its filing country is by construction *not* in Paris, so
if later periods carry more territory-placed firms the Paris share must fall
whatever happened. The third column answers it. Recomputed on the firms with a
**street address alone** — where position is a fact about the firm rather than
about the catalogue — the trend survives, from 82.6% to 42.1%. Both series are
monotone and `checks.py` asserts it.

### The 1945–1962 panel is a thinner sample, not a thinner network

Coverage sits at 81–86% in every period but one. In 1945–1962 only **36.2%** of
the active firms can be placed at all, because **1,483 of its 1,484
unplaceable firms are filed under the transversal *Empire* rubric with no
country**. That is a change in how Mennevée catalogued after the war, not a
change in the empire, and it is why fig58 draws coverage beside the trend
rather than mentioning it in a footnote: a reader comparing panel four with
panel two is comparing two different sampling regimes.

### What these maps are of

They are maps of a **record**. A firm leaves a panel when the compiler stopped
writing about it, which is not the same event as the firm closing, and the
volume of coverage is itself uneven across the five periods — 11,502 drawable
ties in 1914–1929 against 568 after 1962. Read the shares, which have a
denominator inside each period, rather than the densities, which do not.

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
python3 src/split_by_country.py                 # ~2 min, per-territory bundles
python3 src/code_positionality.py               # ~1 min, positionality coding
python3 src/centrality.py                       # ~1 min, exact betweenness
python3 src/geocode.py                          # place firms at city level
python3 src/make_figures.py                     # ~1 min, core figures
python3 src/make_territory_figures.py           # ~1 min, empire + per-territory
python3 src/make_geo_figure.py                  # the empire on the map
python3 src/make_descriptive_figures.py         # figures 8-17, what the data is
python3 src/make_network_figures.py             # ~30 s, figures 18-27 + measures
python3 src/make_node_figures.py                # figures 28-33, node level
python3 src/make_figures.py --lang en            # English label set
python3 src/make_territory_figures.py --lang en
python3 src/make_geo_figure.py --lang en
python3 src/make_descriptive_figures.py --lang en
python3 src/make_network_figures.py --lang en
python3 src/make_node_figures.py --lang en
python3 src/render_png.py                       # ~2 min, PNG of every figure
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
