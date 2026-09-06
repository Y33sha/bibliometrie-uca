# Données dérivées

*À jour le 2026-09-05.*

Une partie du schéma ne porte aucune donnée saisie : ce sont des **dérivés** recalculés à partir d'autres tables — vues matérialisées, tables satellites, colonnes dénormalisées. Ils existent pour accélérer la lecture (éviter à chaque requête des jointures ou des agrégations coûteuses) au prix d'une duplication qu'il faut tenir à jour. Cette page recense ces artefacts et la façon dont leur fraîcheur est maintenue.

## Vues matérialisées

Toutes sont déclarées `WITH NO DATA` et rafraîchies par le pipeline (la plupart en `REFRESH … CONCURRENTLY`, qui suppose un index unique). Aucune n'est écrite directement.

| Vue matérialisée | Dérivée de | Rafraîchie par |
|---|---|---|
| `source_authorship_structures` | `source_authorship_addresses` ⋈ `address_structures` non rejetés ⋈ `perimeter_structures` | phase `affiliations` |
| `authorship_structures` | `source_authorship_structures` ⋈ `source_authorships` | phase `authorships` |
| `publication_structures` | `authorships` ⋈ `authorship_structures` | phase `authorships` |
| `subject_cooccurrences` | paires de sujets co-présents sur une même publication (`publication_subjects`) | phase `subjects` |

## Tables dérivées

- **`perimeter_structures`** : appartenance au périmètre, matérialisée par clôture récursive de `structure_tutelles`. Rematérialisée avant la première phase du pipeline, au démarrage de la phase `affiliations`, et à chaque édition admin qui touche une tutelle ou un périmètre.
- **`publications_detail`** : satellite 1:1 de `publications` (`abstract`, `keywords`, `topics`, `biblio`), recalculé depuis les `source_publications` rattachées.

## Colonnes dérivées

Certaines colonnes dupliquent une information calculable, pour éviter une jointure ou une agrégation en lecture :

| Colonne | Portée par | Rafraîchie par |
|---|---|---|
| `in_perimeter` | `source_authorships` | phase `affiliations` |
| `in_perimeter` | `authorships`, `publications` | phase `authorships` |
| `countries[]` | `source_publications`, `publications` | phase `countries` |
| `pub_count` | `journals`, `publishers` | phase `authorships` |
| `pub_count` | `addresses` | phase `publications` |
| `usage_count` | `subjects` | phase `subjects` |


## Incrémental ou recalcul complet

Les phases coûteuses ne retraitent que ce qui a changé depuis la dernière exécution, repéré par des **flags `dirty`** posés à l'écriture amont : `keys_dirty` sur `source_publications` (clés de rapprochement modifiées → réconciliation des publications), `countries_dirty` sur `source_authorships` (pays à re-détecter). Le traitement traite les lignes marquées puis efface le flag.

Le mode incrémental fait l'hypothèse que l'état antérieur est correct. Une évolution des règles en amont peut donc laisser un **drift** : des dérivés figés sur l'ancienne logique, jamais re-marqués. Plusieurs traitements offrent pour cela un recalcul complet de récupération — par exemple `run_pipeline --only publications --rebuild-publications` (re-marque tout le stock `dirty` avant de le traiter) ou `run_pipeline --only authorships --rebuild-authorships` (purge complète + reconstruction). À lancer après un changement de règles, pour matérialiser ce que le mode incrémental ne verrait pas.
