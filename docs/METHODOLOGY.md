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

Ten stages, each resumable, each writing its own outputs:

1. **`crawl_catalogue.py`** — the 13 index pages → `documents.csv`,
   `document_listings.csv`.
2. **`fetch_extract.py`** — each PDF → gzipped plain text in `data/text/`,
   plus `text_extraction.csv`.
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
4. **`build_network.py`** — observations → nodes, edges, projections, GraphML.
   All five genres are merged by default; `--no-person-index`, `--no-prose`,
   `--no-annotations` and `--no-biographical` drop one each.
5. **`split_by_country.py`** — dataset → per-territory bundles (§5b).
6. **`code_positionality.py`** — people → colonial/native coding (§5c).
6b. **`centrality.py`** — interlock graph → exact betweenness per firm (§5e).
6c. **`geocode.py`** — addresses → a city per firm, below colony level (§5f).
7. **`make_figures.py`** — network → the core figures, HTML and SVG (§5d).
8. **`make_territory_figures.py`** — network → the whole-empire figure, the
   territory matrix and one figure per territory (§5d).
9. **`render_png.py`** — every figure → PNG, one network per file.
10. **`make_geo_figure.py`** — places → the interlock network on the map (§5f).

Figure stages 7 and 8 take `--lang en`, which writes a parallel `figures/en/`
tree with the territory, region and sector labels in English. Firm and person
names are left in French throughout: a company's name is a legal name rather
than a description, and an English rendering of it would be a string that
appears in no archive or authority file. The category vocabulary is a
description and is translated, in `data/reference/labels_en.csv` — 183 rows,
which `checks.py` asserts is complete against the data.

`checks.py` validates the parsers and the built dataset (804 assertions).

## 2b. What is *not* extracted

Extraction of the PDFs is near-complete: 5,867 of 5,920 documents (99.2%), the
rest dead links. Turning that text into ties is not. **3,594 of the 5,867
(61%) yield at least one tie**; the other 2,273 hold 26% of the extracted
characters. When only the dossier parser existed those figures were 2,482
(42%) and 47% — stages 3b–3e, below, are what closed the gap. This section
says what is still in the residue, because a reader is otherwise entitled to
assume the pipeline saw everything.

Sorting the 2,273 zero-tie documents by how much board vocabulary they
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

One further gap is quantified elsewhere: **9,567 parsed ties (12.9%)** are
dropped for want of an identifiable firm (§5). The compiler's annotation leads
are now resolved as far as they go (§4e).

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
parser uses. It yields **14,251 ties over 2,521 firms**, of which 8,421
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
evidence stated by the source. Stage 4 emits 20,208 of these as candidates but
resolves only 2,523 — exact names and catalogue acronyms — because the note is
abbreviated where the company name is not.

`resolve_annotations.py` matches by **token prefix, in order**: every note
token must prefix a name token, and in sequence. "Cotonn. St-Quentin" resolves
to *Cotonnière de Saint-Quentin*; "Bq de Madagascar" to *Banque de
Madagascar*. Prefix matching needs no list of abbreviations, which matters
because the compiler invents them freely. Result: **1,692 ties over 498 firms**,
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

Why only 8% of the 20,554 candidate notes resolve: 4,204 name the firm the
observation already belongs to, and 8,285 name a company absent from this
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
matcher from §4e. **3,060 ties over 719 firms and 687 people**, hand-audited
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

## 5c. Coding positionality in the colonial order

`code_positionality.py` codes each person `colonial` or `native`, with
`intermediate` and `local_non_french_elite` for the two groups the binary
cannot hold. The evidence is the name as printed plus the territory the
person's ties were observed in — onomastic inference and nothing else.

**Every obvious rule is wrong.** Each was measured against all 35,158 names
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
5,839 firms and 79,897 edges: rendered as a node-link diagram it is a solid
disc that shows only that the ink is dense. Every figure is an explicit
subset, and the subset rule is printed with the figure. Figure 1 raises the
threshold to two shared directors, takes the largest component, and keeps the
170 firms of highest weighted degree — 1,162 interlocks. Reading a *global*
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
1914–1929 panel (1,764 interlocks) look *smaller* than pre-1914 (299): the
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

**Figure 4 draws all 5,839 firms and 79,897 interlocks.** At that density a
node-link diagram cannot be read firm by firm, and it is not offered for that.
The question it answers is compositional: are the empire's boards one
integrated elite or separate territorial ones? Colour is the firm's first
territory folded to the three largest, and the answer the figure gives is
"both" — Indochine, Maroc and AOF each hold a visibly distinct lobe, joined
through a dense mixed core. Node radii are 42% of the core figure's and edge
ink 42% of its opacity, because the settings tuned for 170 nodes render 3,085
as a solid disc.

**Nothing is dropped to make the picture tidy.** 98.5% of the firms sit in one
giant component; the other 46 are in 22 tiny ones that a spring layout flings
into the corners. They are packed into a strip below a rule, labelled as
unconnected, rather than being silently cut — a figure captioned "every firm"
has to contain every firm. `checks.py` asserts the drawn node set equals the
graph's, for figure 4 and for each of the 42 territory figures, so the claim
is enforced rather than merely intended.

**Figure 5 is a matrix, not a node-link diagram.** Aggregated to territories
the graph is small (53 nodes) and nearly complete (713 of 1,378 possible pairs
share at least one director), which is exactly the regime where a node-link
diagram degenerates into a scribble and a matrix becomes readable. The cell is
the count of directors holding board seats in both territories; rows and
columns are ordered by size, which is what makes the core-periphery structure
legible. Two things to know before reading it: the shading steps by **rank,
not linearly**, because the counts are heavily skewed and a linear ramp would
put everything but the top two pairs — Maroc–Algérie at 1,086 shared
directors and Maroc–Indochine at 1,024 — in the palest step; and a firm listed in two territories contributes its whole board to
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
at `weight >= 1` (5,758 firms, 39,497 ties) and then displayed on whatever
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
title and is a clean city name (1,692 firms). `head_office_observed` is
transcribed prose — *"Paris, 1, rue de Stockholm. Tél. : LAB. 18-34"* — and
covers 3,970. The first is preferred; the second is parsed only where the
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

**Coverage: 3,138 of 10,705 firms (37%), and 1,393 of the 5,839 in the
interlock graph (45%).** The map draws those. It is not a map of the empire's
firms but of the ones whose address survived, and the unplaced 55% are absent
rather than assumed.

**Three readings the figure would otherwise invite, and why they are wrong.**
A head office is not an operation: a rubber plantation in Cochinchina run from
a Paris office appears at Paris, which is a true fact about control and a
false one about production. A city's size on the map is firms *recorded* there,
inheriting all of §6's coverage unevenness. And ties within a single city
cannot be drawn — an edge from Paris to Paris is a dot — so the 3,275
within-city interlocks appear as a table column rather than on the map, against
7,808 drawn between cities; a reader who counts only the lines undercounts the
network by nearly a third.

The headline result survives all three: 41% of placed firms in the interlock
graph were run from Paris, more than the next 21 cities combined, and the
heaviest lines radiate from Paris rather than running between colonies.

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
python3 src/make_figures.py --lang en            # English label set
python3 src/make_territory_figures.py --lang en
python3 src/render_png.py                       # ~90 s, PNG of every figure
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
