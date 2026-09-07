# Authorships et tables sources

*À jour le 2026-09-05.*

## `authorships` — table consolidée des contributions

Table de liaison recensant les contributions individuelles aux publications. Chaque entrée référence **1 personne**, **1 publication**, *n* structures (via la matview `authorship_structures`). Construite par `application/pipeline/authorships/build_authorships.py` à partir des *authorships* sources.

**Couverture partielle assumée** : la table ne contient des entrées que pour les signataires ayant une `person_id`. Les co-auteurs hors périmètre n'apparaissent pas ici ; la liste exhaustive des auteurs d'une publication se lit dans `source_authorships`.

Colonnes notables :

- `person_id`
- `in_perimeter` : TRUE si l'auteur signe cette publication depuis une structure du périmètre
- `author_position` : position dans la liste d'auteurs
- `is_corresponding` : auteur correspondant
- `roles` (text[]) : rôles (auteur, directeur, rapporteur — pour theses.fr)

`authorship_structures (authorship_id, structure_id)` porte les affiliations résolues. C'est une **vue matérialisée**, réunion des `source_authorship_structures` des signatures reliées à l'authorship, rafraîchie par le pipeline en fin de phase `authorships`.

**Une édition d'administration ne la rafraîchit pas.** La review d'un lien adresse ↔ structure et l'assignation d'une signature orpheline recalculent `in_perimeter` en direct, mais l'agrégation des structures reste sur l'état de la dernière exécution du pipeline.

**Cohérence avec les sources** : la table est **entièrement dérivée** des `source_authorships`. `in_perimeter`, les liens via `authorship_structures`, `is_corresponding`, `author_position` et `roles` en sont des consolidations, par union ou par priorité de source. Elle ne porte aucun état propre : les décisions humaines vivent dans les deux stores ci-dessous.

### Décisions humaines

Deux stores portent les arbitrages saisis à la main, et survivent aux reconstructions de la table dérivée :

- **`rejected_authorships`** — paires (publication, personne) écartées. Clé primaire `(publication_id, person_id)`.
- **`confirmed_authorships`** — signatures épinglées sur une personne. Clé primaire `source_authorship_id`.

## Tables sources

Toutes les sources partagent les mêmes tables, discriminées par la colonne `source` (enum `source_type` : hal, openalex, wos, scanr, theses, crossref, datacite).

- **`source_publications`** : un enregistrement par document par source. Relié à `publications` via `publication_id` (peut être NULL si pas encore rattaché). Contient les métadonnées (doc_type non mappé, oa_status, abstract, keywords, topics, biblio, meta).
- **`source_authorships`** : une signature — un auteur sur un document source. `person_id` et `authorship_id` la relient à la personne et à l'authorship consolidés, `identity_id` à son identité d'auteur. Ses adresses passent par `source_authorship_addresses`, d'où la matview `source_authorship_structures` dérive ses structures.
- **`author_identifying_keys`** : les attributs d'identité d'une signature — nom normalisé et identifiants. Une ligne par identité distincte, que `source_authorships.identity_id` référence : toutes les signatures de même identité la partagent.
- **`source_authorship_addresses`** : table de liaison `source_authorships ↔ addresses`. Permet aux normalizers de partager une même chaîne d'adresse normalisée (`addresses.raw_text` → `addresses.normalized_text`) entre plusieurs authorships, et alimente la résolution structure ↔ adresse de la phase `affiliations`.
- **`staging`** : une ligne par document moissonné. Porte le payload brut de la source, vidé après normalisation, et les marqueurs d'absence — `not_found_at` quand la source n'a pas rendu un document cherché, `disappeared_at` quand elle cesse de le rendre. Son cycle de vie relève du [moissonnage](../pipeline/02-extract.md).
- **`doi_lookups`** : DOI cherchés en vain dans une source. `next_retry` porte la date de la prochaine tentative, NULL valant « plus jamais ».

## Propriété des tables

| Table | Auteur | Écrit par |
|---|---|---|
| `staging` | pipeline | extracteurs (`infrastructure/sources/*/extract_*.py`, cross-imports) |
| `doi_lookups` | pipeline | cross-imports DOI (`infrastructure/sources/*/fetch_missing_doi.py`) |
| `source_publications` | pipeline | `application/pipeline/normalize/normalize_*.py` |
| `author_identifying_keys` | pipeline | `normalize_*.py` (via `_authorships_batch.py`) |
| `source_authorships` | mixte | `normalize_*.py` (pipeline) ; `in_perimeter` par la phase `affiliations`, `authorship_id` par la phase `authorships` ; `person_id` par le pipeline ou en admin (orphan-assign) |
| `source_authorship_addresses` | pipeline | `normalize_*.py` (via `_authorships_batch.py`) |
| `authorships` | pipeline | `build_authorships.py` (consolidée depuis les sources) |
| `rejected_authorships` | admin | `application/services/authorships/core.py` |
| `confirmed_authorships` | admin | `application/services/authorships/assign_orphans.py` |
