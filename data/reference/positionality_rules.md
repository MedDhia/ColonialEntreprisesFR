# Positionality coding — reference lists and rationale

`src/code_positionality.py` codes each person in the dataset by their position
in the colonial order. The only evidence available is the name as printed,
plus the territory the tie was observed in, so the coding is **onomastic
inference and nothing more**. This file records the lists the coder uses and
why each rule is shaped the way it is, so the decisions can be audited and
edited.

## Why the obvious rules do not work

Each of these was tried against the 24,458 person records and rejected:

| Rule | Hits | Why rejected |
|---|---|---|
| Vietnamese surname `Le` | 124 | All French: *Le Bret*, *Le Play*, *Le Trocquer*. The Vietnamese surname Lê collides with the French article. |
| Vietnamese particle `Van` | 163 | All Dutch/Flemish: *Van Nierop*, *Van Brée*, *Van den Ven*. |
| Malagasy prefix `Ra-` | 51 | All French: *Rastoin*, *Rabeau*, *Raty*, and every *Raymond*/*Raoul*/*André*. |
| Ottoman title `Bey`/`Pacha` alone | ~60 | Granted to Europeans in Egyptian and Ottoman service: *Boinet Bey*, *H. Naus bey*, *Ch. Audebeau bey*, *Aleco Bey Pangiris*. A rank, not an origin. |
| Short-syllable triples as Chinese | 91 | Caught *Max Katz*, *Louis Bovet*, *Paul Blanc*. |

The surviving rules therefore require a **conjunction**: an indigenous-name
pattern *and* a plausible territory, and for Vietnamese a full name structure
rather than a single token.

## Groups coded

- `maghrebi_arab_berber` — Arabic/Berber given names, the particles
  `ben`/`bel`/`bou`/`ould`/`aït`/`el`, or Maghrebi religious and makhzen
  honorifics (`si`, `sidi`, `hadj`, `cheikh`, `caïd`, `bachagha`, `moulay`).
  Territory must be Maghreb, AOF, AEF or Madagascar-Djibouti.
- `vietnamese` — a Vietnamese surname followed by a Vietnamese middle
  syllable (`Nguyen Van …`, `Truong Van …`, `Dang Ngoc …`), or a hyphenated
  triple (`NGUYEN-VAN-THINH`). Territory must be Indochina.
- `chinese_indochinese` — curated only (see list below). No general pattern
  reached acceptable precision.
- `west_african` — curated surname list, exact token match, territory AOF/AEF.
- `syro_lebanese` — curated Levantine merchant and notable surnames.
- `ottoman_egyptian` — Turkish/Egyptian/Armenian/Greek elite names in the
  Near East pages. **Not** coded `native`: see below.
- `malagasy` — prefixes `Rakoto-`, `Rabe-`, `Ratsi-`, `Randria-`, `Razafi-`,
  `Ramana-`, `Andria-` with a minimum stem length. **Zero matches** in this
  dataset, which is a finding rather than a gap.

## Why `ottoman_egyptian` is not `native`

The Near East index pages cover French business interests in Egypt, the
Ottoman Empire, Turkey, Greece and the Syria-Lebanon mandate. Only the last
was under French colonial rule. An Egyptian pasha on the board of a
French-owned Egyptian company is a local elite in a state that was formally
Ottoman and effectively British-occupied — not a colonial subject of France.
Coding him `native` alongside a Moroccan notable would merge two different
political positions. These rows are coded `local_non_french_elite`, with the
country retained so the researcher can decide.

Syria-Lebanon is the exception and is coded `native` when the name matches
the Levantine list, since the mandate was French.

## Curated lists

### Chinese-Indochinese (`chinese_indochinese`)
Hui-Bon-Hoa, Hui Bon Hoa, Quach Dam, Ban Hap, Chan Yok Lam, Tang Keng Sen,
Ly Hoa, Ma Tuyen, Truong Van Ben, Wang Tai

Note *Truong Van Ben* (soap manufacturer, Saigon) is Vietnamese and appears
in the Vietnamese rule; he is listed here only because the sources sometimes
render Sino-Vietnamese merchants ambiguously. The coder prefers the
Vietnamese rule when both match.

### West African (`west_african`)
diop, diagne, ndiaye, fall, gueye, sarr, sow, diallo, cisse, traore, keita,
coulibaly, konate, camara, toure, sylla, bamba, ouattara, kone, diarra,
dembele, sagna, thiam, niang, seck, mbaye, badji, sonko, mbodj, ndour, ka,
guisse, wade, lo, samb

`faye` and `ba` are deliberately **excluded**: both are also common French
surnames (*J. Faye*) and short enough to match fragments.

### Levantine / Syro-Lebanese (`syro_lebanese`)
khoury, khouri, haddad, sursock, sabbagh, aoun, chiha, pharaon, trad,
bustros, tabet, edde, gemayel, naccache, corm, debbas, takla, zalzal, arida,
dagher, nahas, kettaneh, beyhum, chehab, tueni, salam, daouk, bassoul

### Intermediate: `maghrebi_jewish`
`amar`, `benchimol`, `bensimon`, `corcos`, `toledano`, `pinto`, `assouline`,
`sebag`, `boccara`, `guez`, `chemla`, `bessis`, `nataf`, `hayat`, `zerbib`,
`smadja`, `attal`, `dahan`, `elmaleh`, `abitbol`, `azoulay`, `bouhsira`

These are coded `intermediate`, never `native` or `colonial`. Algerian Jews
became French citizens by the Crémieux decree of 1870 while Muslim Algerians
remained subjects; Moroccan and Tunisian Jews did not. Their position in the
colonial order is genuinely between the two and is the subject of a
substantial literature. `cohen`, `levy`, `benhamou` and similar are **not**
on the list: they are equally common among metropolitan French Jews, so the
name carries no information about position.

## Residual category

A person whose name matches no indigenous pattern is coded `colonial` with
`confidence = low` and `evidence = residual`. This is an inference from
absence: in a corpus of French colonial company boards, an unmarked name is
overwhelmingly European. It is not positive evidence about that individual,
and should not be reported as though it were.
