# Données dérivées

*À jour le 2026-10-12.*

Certaines données sont des **dérivés** recalculés à partir d'autres tables — vues matérialisées, tables satellites, colonnes dénormalisées. Ils existent pour accélérer la lecture (éviter à chaque requête des jointures ou des agrégations coûteuses) au prix d'une duplication qu'il faut tenir à jour. Cette page recense ces artefacts et la façon dont leur fraîcheur est maintenue.

## Vues matérialisées

Toutes sont déclarées `WITH NO DATA` et rafraîchies par le pipeline (la plupart en `REFRESH … CONCURRENTLY`, qui suppose un index unique). Aucune n'est écrite directement.

| Vue matérialisée | Dérivée de | Rafraîchie par |
|---|---|---|
| `source_contribution_structures` | adresses (`address_structures` non rejetés), ROR, structures HAL et structures de thèse des contributions sources ⋈ `perimeter_structures` | phase `affiliations` |
| `contribution_structures` | `source_contribution_structures` ⋈ `source_contributions` | phase `contributions` |
| `publication_structures` | `contributions` ⋈ `contribution_structures` | phase `contributions` |
| `subject_cooccurrences` | paires de sujets co-présents sur une même publication (`publication_subjects`) | phase `subjects` |

## Tables dérivées

- **`perimeter_structures`** : appartenance au périmètre, matérialisée par clôture récursive de `structure_parents`. Rematérialisée avant la première phase du pipeline et à chaque édition admin qui touche une tutelle ou un périmètre.
- **`publications_detail`** : satellite 1:1 de `publications` (`abstract`, `keywords`, `topics`, `biblio`), recalculé depuis les `source_records` rattachées.

## Colonnes dérivées

Certaines colonnes dupliquent une information calculable, pour éviter une jointure ou une agrégation en lecture :

| Colonne | Tables | Rafraîchie par |
|---|---|---|
| `perimeter_evidence`, d'où `in_perimeter` | `source_contributions` | phase `affiliations` |
| `perimeter_evidence`, d'où `in_perimeter` | `contributions`, `publications` | phase `contributions` |
| `countries[]` | `addresses`, `source_contributions`, `source_records`, `publications` | phase `countries` |
| `publication_count` | `journals`, `publishers` | phase `contributions` |
| `publication_count` | `addresses` | phase `publications` |
| `usage_count` | `subjects` | phase `subjects` |


## Incrémental ou recalcul complet

Les phases coûteuses retraitent seulement ce qui a changé depuis la dernière exécution. Une **marque de recalcul** désigne les lignes à reprendre :

- `keys_dirty` sur `source_records` : regroupement des publications à refaire (phase `publications`) ;
- `contributions_dirty` sur `publications` : groupes d'auteurs à recalculer (phase `author_grouping`) ;
- `authors_hash` vide sur `source_records` : contributions sources à resynchroniser à la prochaine normalisation de l'enregistrement source (phase `normalize`) ;
- `subjects_ingested_at` vide sur `publications` : sujets à ingérer (phase `subjects`) ;
- `candidates_dirty` sur `addresses` : pays à détecter et à résoudre ;
- `countries_dirty` sur `addresses` et `source_contributions` : pays à recalculer.

L'écriture amont pose la marque. Le traitement reprend les lignes marquées, puis efface la marque.

Le mode incrémental suppose que l'état antérieur est correct. Une règle modifiée laisse donc des dérivés calculés selon l'ancienne règle, jamais marqués. Les [options de reconstruction](../exploitation/03-pipeline.md#reconstructions) posent la marque sur tout le stock. Le traitement ordinaire applique ensuite la règle modifiée.
