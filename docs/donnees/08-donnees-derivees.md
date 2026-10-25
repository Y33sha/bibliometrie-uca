# Données dérivées

*À jour le 2026-10-25.*

Certaines données sont des **dérivés** recalculés à partir d'autres tables — vues matérialisées, tables satellites, colonnes dénormalisées. Ils existent pour accélérer la lecture (éviter à chaque requête des jointures ou des agrégations coûteuses) au prix d'une duplication qu'il faut tenir à jour. Cette page recense ces artefacts et la façon dont leur fraîcheur est maintenue.

## Vues matérialisées

Le pipeline les rafraîchit, la plupart en `REFRESH … CONCURRENTLY`, qui suppose un index unique. Aucune n'est écrite directement.

| Vue matérialisée | Dérivée de | Rafraîchie par |
|---|---|---|
| `source_contribution_structures` | adresses (`address_structures` non rejetés), ROR, structures HAL et structures de thèse des contributions sources ⋈ `perimeter_structures` | phase `affiliations` |
| `contribution_structures` | `source_contribution_structures` ⋈ `source_contributions` | phase `finalize` |
| `publication_structures` | `contributions` ⋈ `contribution_structures` | phase `finalize` |
| `publication_rors` | ROR des contributions sources alignées des auteurs (`source_contribution_rors`) et des structures de `publication_structures`, avec leurs ancêtres de `ror_relations` ; `cited` distingue les ROR cités | phase `finalize` |
| `subject_cooccurrences` | paires de sujets co-présents sur une même publication (`publication_subjects`) | phase `subjects` |

## Tables dérivées

- **`perimeter_structures`** : appartenance au périmètre, matérialisée par clôture récursive de `structure_parents`. Rematérialisée avant la première phase du pipeline et à chaque édition admin qui touche une tutelle ou un périmètre.
- **`publications_detail`** : satellite 1:1 de `publications` (`abstract`, `keywords`, `topics`, `biblio`), recalculé depuis les `source_records` rattachées.

## Colonnes dérivées

Certaines colonnes dupliquent une information calculable, pour éviter une jointure ou une agrégation en lecture :

| Colonne | Tables | Rafraîchie par |
|---|---|---|
| `perimeter_evidence`, d'où `in_perimeter` | `source_contributions` | phase `affiliations` |
| `perimeter_evidence`, d'où `in_perimeter` | `contributions`, `publications` | phase `finalize` |
| `countries[]` | `addresses`, `source_contributions`, `source_records`, `publications` | phase `countries` |
| `is_corresponding`, `roles`, `perimeter_evidence` | `contributions` | phase `author_grouping` |
| `publication_count` | `serials`, `publishers` | phase `finalize` |
| `publisher_id` | `serials` | phase `finalize`, d'après les publications |
| `publication_count` | `addresses` | phase `publications` |
| `usage_count` | `subjects` | phase `subjects` |


## Incrémental ou recalcul complet

Les phases coûteuses retraitent seulement ce qui a changé depuis la dernière exécution. Une **file d'attente** du schéma `queues` liste les lignes à reprendre :

| File | Lignes à reprendre | Phase |
|---|---|---|
| `source_record_keys_queue` | enregistrements sources à rattacher à leur publication | `publications` |
| `publication_contributions_queue` | publications dont les contributions sont à réaligner | `author_grouping` |
| `contribution_attributes_queue` | contributions dont les attributs sont à recomposer | `author_grouping` |
| `contribution_resolution_queue` | contributions dont la personne est à redécider | `persons` |
| `address_candidates_queue` | adresses dont les pays sont à détecter et à résoudre | `countries` |
| `address_countries_queue` | adresses dont le pays change | `countries` |
| `source_contribution_countries_queue` | contributions sources dont les pays sont à recalculer | `countries` |

Marquer une ligne, c'est insérer son identifiant dans la file, avec un numéro de marquage. Le traitement relève la file, reprend les lignes relevées, puis supprime les marquages relevés. Un marquage fait pendant le traitement reste en file pour l'exécution suivante.

Deux marques sont des colonnes :

- `authors_hash` vide sur `source_records` : contributions sources à resynchroniser à la prochaine normalisation de l'enregistrement source (phase `normalize`) ;
- `subjects_ingested_at` vide sur `publications` : sujets à ingérer (phase `subjects`).

Le mode incrémental suppose que l'état antérieur est correct. Une règle modifiée laisse donc des dérivés calculés selon l'ancienne règle, jamais marqués. Les [options de reconstruction](../exploitation/03-pipeline.md#reconstructions) marquent tout le stock. Le traitement ordinaire applique ensuite la règle modifiée.
