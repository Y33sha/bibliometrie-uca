# Inventaire des accès aux tables — couches d'accès aux données

État des lieux de la phase A du chantier `CODE_couches-acces-donnees` : pour chaque table, quelles couches la lisent et l'écrivent, et tri agrégat métier / service de pipeline.

## Méthode

Un relevé par couche (lecture de tout le SQL — `text()`, f-strings, fragments), croisé avec `infrastructure/db/schema.sql` pour distinguer tables, vues et vues matérialisées. Couverture : 15 modules `repositories/`, 24 `queries/pipeline/`, 32 `queries/api/`.

## Légende des couches

- **R** — `infrastructure/repositories/` (mutations pilotées par l'admin et l'API : fusions, rejets, création)
- **P** — `infrastructure/queries/pipeline/` (accès BDD des phases du pipeline, lecture et écriture)
- **A** — `infrastructure/queries/api/` (read-models du frontend — **lecture seule**, vérifié : aucune écriture)
- **S** — `infrastructure/sources/common.py` (persistance d'extraction, en instance de déménagement — phase E en pause du chantier `CODE_perimetre-infrastructure-sources`)
- **C** — `interfaces/cli/` (scripts écrivant en base directement, hors des couches)

La colonne « écrite » est précise ; la colonne « lue » est au niveau couche (une couche est marquée dès qu'un de ses modules lit la table).

## Agrégats métier — écrits par le domaine (R) *et* construits par le pipeline (P)

| Table | Écrite | Lue |
|---|---|---|
| `source_publications` | R, P | R, P, A |
| `source_authorships` | R, P | R, P, A |
| `authorships` | R, P | R, P, A |
| `publications` | R, P | R, P, A |
| `addresses` | R, P | R, P, A |
| `persons` | R, P | R, P, A |
| `journals` | R, P | R, P, A |
| `publishers` | R, P | R, P, A |
| `person_name_forms` | R, P | R, P, A |
| `address_structures` | R, P | R, P, A |
| `distinct_publications` | R, P | R, P, A |
| `apc_payments` | R, P | A |

## Agrégats et satellites — écrits par le domaine seul (R)

| Table | Écrite | Lue |
|---|---|---|
| `structures` | R | R, P, A |
| `structure_name_forms` | R | R, P, A |
| `structure_relations` | R | R, A |
| `journal_name_forms` | R | R |
| `publisher_name_forms` | R | R |
| `publications_detail` | R | R, A |
| `person_identifiers` | R | R, P, A |
| `distinct_persons` | R | A |
| `confirmed_authorships` | R | R, P |
| `rejected_authorships` | R | R, P |
| `persons_rh` | R, C | R, P, A |
| `config` | R | A, S |
| `audit_log` | R | — |
| `perimeters` | R | R |
| `perimeter_structures` | R | R, A |

## Tables de service du pipeline

| Table | Écrite | Lue | Note |
|---|---|---|---|
| `staging` | P, S | P | écrite à la fois par l'extraction (S) et par normalize (P) |
| `doi_lookups` | S | S | accédée **uniquement** depuis `sources/common.py` |
| `doi_prefixes` | R | R, A, S | table de service, mais **derrière un repository** |
| `author_identifying_keys` | P | R, P, A | |
| `source_authorship_addresses` | P | R, P, A | |
| `subjects` | P | P, A | vocabulaire construit par la phase subjects |
| `publication_subjects` | P | P, A | |
| `publication_relations` | P | P, A | rebuild complet (DELETE puis INSERT) |
| `pipeline_phase_executions` | orchestrateur | A | écrite hors des trois couches |
| `candidate_dois` (VUE) | — | R, S | vue dérivée, lecture seule |
| `source_authorship_structures` (MATVIEW) | P (refresh) | P, A | |
| `authorship_structures` (MATVIEW) | P (refresh) | P, A | |
| `publication_structures` (MATVIEW) | P (refresh) | P, A | |
| `subject_cooccurrences` (MATVIEW) | P (refresh) | P | |

## Référence / vocabulaire

| Table | Écrite | Lue | Note |
|---|---|---|---|
| `countries` | seed (migration) | R, P, A | référentiel ISO, non muté au runtime |
| `place_name_forms` | C | P | écrite seulement par les scripts CLI de gestion des toponymes |

## Constats

1. **`queries/api` est strictement en lecture seule** — le CQRS-read y est propre et net.
2. **Les agrégats cœur sont écrits par deux couches** : `repositories/` pour les mutations admin/API (fusions, rejets), `queries/pipeline/` pour la construction ETL. Aucune de ces tables n'a de couche propriétaire unique — c'est le fond du problème, pas un accident.
3. **`doi_prefixes` est l'incohérence-type** : une table de service du pipeline (cache préfixe → Registration Agency + éditeur, peuplée par `resolve_ra` et `publishers_journals`) accédée via un **repository**, alors que `staging` et `doi_lookups`, de même nature, sont hors `repositories/`.
4. **`doi_lookups` n'a pas de maison** : accédée seulement depuis `sources/common.py`, ni repository ni couche pipeline. C'est l'objet direct de la phase E en pause du chantier `CODE_perimetre-infrastructure-sources`.
5. **Les CLI contournent le layering** : ~27 scripts `interfaces/cli/` écrivent en base directement — surtout des `oneshot/` jetables (où c'est défendable), mais aussi quelques `maintenance/` et `imports/` permanents.
