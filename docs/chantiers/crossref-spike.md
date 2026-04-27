# Spike CrossRef — résultats phase 0

_Échantillon : 100 DOI tirés (sur 100 demandés). Voir [chantiers/crossref.md](crossref.md) pour le contexte._

## Statut des appels API

| Bucket | total | trouvés | introuvables | erreurs |
|---|---:|---:|---:|---:|
| 2010-2014 | 16 | 14 | 2 | 0 |
| 2015-2019 | 40 | 35 | 5 | 0 |
| 2020-2024 | 44 | 37 | 7 | 0 |
| **total** | **100** | **86** | **14** | **0** |

## Couverture ORCID par bucket

| Bucket | trouvés | publis ≥1 ORCID | % publis | auteurs | auteurs ORCID | % auteurs | publis avec authenticated-orcid:true |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2010-2014 | 14 | 0 | 0.0% | 138 | 0 | 0.0% | 0 |
| 2015-2019 | 35 | 9 | 25.7% | 3238 | 12 | 0.4% | 1 |
| 2020-2024 | 37 | 11 | 29.7% | 712 | 17 | 2.4% | 1 |
| **total** | **86** | **20** | **23.3%** | **4088** | **29** | **0.7%** | **2** |

## Présence des autres champs (par bucket)

| Bucket | trouvés | relation | license | funder | ROR | abstract | references |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2010-2014 | 14 | 0 | 10 | 0 | 0 | 1 | 12 |
| 2015-2019 | 35 | 2 | 19 | 3 | 3 | 13 | 22 |
| 2020-2024 | 37 | 0 | 23 | 4 | 1 | 12 | 12 |
| **total** | **86** | **2** | **52** | **7** | **4** | **26** | **46** |

## Distribution des `type` CrossRef

- `journal-article` : 48
- `book-chapter` : 17
- `book` : 4
- `dissertation` : 4
- `monograph` : 4
- `proceedings-article` : 3
- `edited-book` : 2
- `journal-issue` : 2
- `posted-content` : 1
- `peer-review` : 1

## Types de relations observés

- `is-preprint-of` : 1
- `is-review-of` : 1

## Match des ORCIDs CrossRef avec `person_identifiers` UCA

_Pour chaque ORCID rencontré dans CrossRef, on regarde s'il existe côté UCA et son statut._

- `unknown_in_uca` : 14
- `pending` : 12
- `confirmed` : 3

## doc_type canonique vs `type` CrossRef

_86 paires observées. Sert d'amorce au mapping `_SOURCE_MAPS["crossref"]`._

| canonique | CrossRef type | subtype | n |
|---|---|---|---:|
| article | journal-article | — | 29 |
| book_chapter | book-chapter | — | 16 |
| conference_paper | journal-article | — | 6 |
| book_review | journal-article | — | 4 |
| book | monograph | — | 4 |
| review | journal-article | — | 3 |
| book | book | — | 3 |
| conference_paper | proceedings-article | — | 3 |
| thesis | dissertation | — | 3 |
| book | edited-book | — | 2 |
| poster | journal-article | — | 2 |
| data_paper | journal-article | — | 2 |
| book_chapter | journal-article | — | 1 |
| conference_paper | book-chapter | — | 1 |
| other | journal-article | — | 1 |
| other | journal-issue | — | 1 |
| preprint | posted-content | preprint | 1 |
| preprint | peer-review | — | 1 |
| article | journal-issue | — | 1 |
| book_chapter | book | — | 1 |
| conference_paper | dissertation | — | 1 |

