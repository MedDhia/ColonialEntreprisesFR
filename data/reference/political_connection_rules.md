# Coding companies by political connection

Read this before using `company_political.csv`. It states what the variable
means, the rules that produce it, the rules that were considered and rejected,
and the four things the coding cannot do.

## The definition

A firm is **politically connected** when at least one person holding a board
seat in it is attested, anywhere in the corpus, as holding an office of state.
This follows the standard definition in the political-economy literature —
Faccio's is a member of parliament, a minister, or a head of state, or a close
relation of one — with one extension the setting requires: **the colonial
executive counts**. A governor-general, a résident général or a résident
supérieur was the state in the territory a colonial company operated in. He
signed its concessions, set the labour regime it recruited under, and allocated
the land it planted. Excluding him because he never stood for election would
measure the metropolitan half of a colonial state and call it the whole.

## The evidence, and where each piece comes from

| Class | Offices | Source |
|---|---|---|
| `executive` | minister, under-secretary of state, keeper of the seals, president of the Republic, governor-general, lieutenant-governor, résident général, résident supérieur, haut-commissaire, commissaire de la République, governor of a named colony | `person_offices.csv` |
| `legislature` | deputy, senator | `person_mandates.csv`, `roster_mandates.csv` |
| `administration` | administrateur / inspecteur des colonies, administrateur des services civils, secrétaire général du gouvernement, director of political or economic affairs, conseiller d'État, prefect, sub-prefect, ambassador, ministre plénipotentiaire, consul general, trésorier-payeur général, governor of the Banque de France or the Crédit foncier, Conseil supérieur des colonies | `person_offices.csv` |
| `local` | conseiller général, mayor | `person_offices.csv` |
| `proxy` | a director who is a named relative of a parliamentarian, per the compiler's own genealogy | `affiliations_roster.csv`, `held_by = relative` |

## `connection_tier`

Ordinal, 0–4. The highest class attested on the board sets the tier.

| Tier | Name | Rule |
|---|---|---|
| 4 | `executive` | a minister, head of state, or colonial governor sat on the board |
| 3 | `legislature` | a deputy or senator sat on the board |
| 2 | `administration` | a senior state official or colonial administrator sat on the board |
| 1 | `local_or_proxy` | municipal or departmental office only, or connection only through a relative |
| 0 | `none` | no office attested for any board member |

**The ordering is an assumption, not a finding.** Ranking a minister above a
deputy follows Faccio and is defensible; ranking a governor-general *with* a
minister rather than below him is a judgement specific to the colonial setting
and argued above. If your design disagrees, the six `has_*` flags and the six
`n_*` counts are all in the file and the tier is reproducible from them in one
line. Nothing downstream depends on the tier that does not also report the
flags.

## `sitting` against `former`, which is the distinction that matters most

A firm whose director was a **sitting** deputy is a different object from one
whose director was a **retired** governor-general. The first is a conflict of
interest running in real time; the second is a revolving door. `former` is read
from the source's own wording — `ancien`, `ex-`, `ci-devant` before the office,
and `honoraire`, `en retraite`, `démissionnaire` after it — and the two are
never summed. `has_sitting` and `has_former` are separate columns, and a firm
can carry both.

Where the source does not say, `former` is `0`. That is a floor, not a
measurement: the corpus omits `ancien` far more often than it omits an office.
**Read `n_former` as a lower bound and `n_sitting` as an upper one.**

## `concurrent`, and why most pairs cannot be tested

A tie observed in 1950 and a mandate held from 1919 to 1932 are both attached
to the firm, and the base coding does not require them to overlap. Where both
the tie year and the office span are known, `n_concurrent` counts the
director–firm pairs whose office overlapped a year the tie was actually
observed. `n_testable` reports how many pairs could be tested at all.

`n_concurrent` is not a corrected version of `n_connected`; it is a much
smaller, much better-evidenced subset. Use it when the claim is about a live
conflict of interest. Use `n_connected` when the claim is about a firm
recruiting from the political class, which does not require simultaneity.

## Indirect connection

`n_connected_neighbours` counts the firms sharing at least one director with
this one that are themselves connected. `indirect_only = 1` marks a firm with
no connected director of its own but a connected neighbour. This is **not**
folded into `connection_tier`, because being one interlock step from a
minister's board is a different construct from having a minister on yours, and
collapsing them would let the variable inflate without limit as the network
grows.

## Confidence

| Value | Rule |
|---|---|
| `high` | the connection rests on a roster entry, or on two or more independent mentions |
| `medium` | one apposition or bracket mention |
| `low` | the connecting person's key has no forename attested, or the only evidence is a footnote career line |

`low` is not a small residue and should not be dropped silently — report what
happens to your result when you exclude it.

## Rules considered and rejected

- **Military rank as a political connection.** `général`, `colonel`,
  `capitaine` attach to hundreds of directors in this corpus, largely as
  honorifics. Coding them would make nearly every board connected and the
  variable would mean nothing. A general who was also a governor-general is
  captured by the office, not by the rank.
- **Chamber-of-commerce and consular-court office.** `président de la chambre
  de commerce`, `juge au tribunal de commerce`. These are elected public
  offices and a case can be made, but they are business self-government rather
  than the state, and including them would blur exactly the boundary the
  variable exists to draw.
- **The Légion d'honneur.** A state decoration held by a very large share of
  the men here. It records that the state noticed someone, not that he held
  power in it.
- **Marriage into a political family, beyond the compiler's own genealogy.**
  `proxy` uses only ties the source itself traces to a named relative of a
  named parliamentarian. Inferring further kinship from shared surnames would
  manufacture connections at scale — `Dior`, `Wendel` and `Reille` each cover
  several unrelated men in this dataset.
- **Foreign offices.** A British Minister of Shipping and an Italian senator
  both appear in the corpus on French colonial boards. Both are real; neither
  is an office of the French state, and coding them beside one would make the
  column mean two things. Rejected at extraction, in `parse_offices.py` and
  `parse_mandates.py`.

## The four things this coding cannot do

1. **It cannot establish that a connection was used.** It records co-presence
   of an office and a board seat. Whether the office was exercised on the
   firm's behalf is not in this dataset and generally not in the source.
2. **It cannot be read as a rate.** Coverage is uneven by territory and period
   (METHODOLOGY §6). A territory whose documents the compiler read closely will
   show more connections than one he did not, for reasons that have nothing to
   do with its firms.
3. **It cannot support a claim about an individual firm's cleanliness.**
   `connection_tier = 0` means no office was found, which is not the same as
   no office having been held. Absence here is weak evidence.
4. **It cannot be compared across `source_genre` without care.** The roster
   genre exists precisely to record political connection, so firms with roster
   evidence are connected at a far higher rate by construction. Hold the genre
   constant, or say that you did not.
