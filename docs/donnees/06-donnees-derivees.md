# Données dérivées

*À jour le 2026-06-30.*

Une partie du schéma ne porte aucune donnée saisie : ce sont des **dérivés** recalculés à partir d'autres tables — vues matérialisées, tables satellites, colonnes dénormalisées. Ils existent pour accélérer la lecture (éviter à chaque requête des jointures ou des agrégations coûteuses) au prix d'une duplication qu'il faut tenir à jour. Cette page recense ces artefacts et la façon dont leur fraîcheur est maintenue.

## Vues matérialisées

Toutes sont déclarées `WITH NO DATA` et rafraîchies par le pipeline (la plupart en `REFRESH … CONCURRENTLY`, qui suppose un index unique). Aucune n'est écrite directement.

| Vue matérialisée | Dérivée de | Rafraîchie par |
|---|---|---|
| `source_authorship_structures` | `source_authorship_addresses` ⋈ `address_structures` confirmés ⋈ `perimeter_structures` | phase `affiliations` |
| `authorship_structures` | `source_authorship_structures` ⋈ `source_authorships` | phase `authorships` |
| `publication_structures` | `authorships` ⋈ `authorship_structures` | phase `authorships` |
| `subject_cooccurrences` | paires de sujets co-présents sur une même publication (`publication_subjects`) | phase `subjects` |
| `person_identifier_keys` | `person_identifiers` (substrat de la file admin « conflits d'identifiant ») | phase `persons` |

## Tables dérivées

- **`perimeter_structures`** : appartenance au périmètre, matérialisée par clôture récursive des tutelles (`structure_relations`). Rematérialisée en début de phase `affiliations`.
- **`publications_detail`** : satellite 1:1 de `publications` (`abstract`, `keywords`, `topics`, `biblio`), recalculé depuis les `source_publications` rattachées.

## Colonnes dérivées

Certaines colonnes dupliquent une information calculable, pour éviter une jointure ou une agrégation en lecture :

- `in_perimeter` sur `source_authorships`, `authorships` et `publications` (rollup d'affiliation).
- `countries[]` sur `source_authorships`, `source_publications` et `publications`.
- `pub_count` sur `journals`, `publishers` et `addresses`.
- `usage_count` sur `subjects`.

## Incrémental ou recalcul complet

Les phases coûteuses ne retraitent que ce qui a changé depuis le dernier run, repéré par des **flags `dirty`** posés à l'écriture amont : `keys_dirty` sur `source_publications` (clés de rapprochement modifiées → réconciliation des publications), `countries_dirty` sur `source_authorships` (pays à re-détecter). Le traitement traite les lignes marquées puis efface le flag.

Le mode incrémental fait l'hypothèse que l'état antérieur est correct. Une évolution des règles en amont peut donc laisser un **drift** : des dérivés figés sur l'ancienne logique, jamais re-marqués. Plusieurs traitements offrent pour cela un recalcul complet de récupération — par exemple `run_pipeline.py --only publications --rebuild-publications` (re-marque tout le stock `dirty` avant de le traiter) ou `run_pipeline.py --only authorships --rebuild-authorships` (purge complète + reconstruction). À lancer après un changement de règles, pour matérialiser ce que le mode incrémental ne verrait pas.
