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

`authorship_structures (authorship_id, structure_id)` porte les affiliations résolues. C'est une **`MATERIALIZED VIEW`** (pas une table) : union des `source_authorship_structures` des `source_authorships` reliées à l'authorship, rafraîchie (`REFRESH … CONCURRENTLY`) **uniquement par le pipeline** (fin de phase `authorships`). Les actions admin (review adresse↔structure, assign orphelin) recalculent `in_perimeter` en direct sans toucher à la matview : l'agrégation des structures dérivées reste sur l'état du dernier run. Index unique `(authorship_id, structure_id)` + index `(structure_id)` ; pas de FK (le nettoyage d'une authorship supprimée se fait au refresh).

**Cohérence avec les sources** : la table est **entièrement dérivée** des `source_authorships` — `in_perimeter`, les liens via `authorship_structures`, `is_corresponding`, `author_position`, `roles` sont des consolidations (union ou priorité par source) des authorships sources. Le build (`application/pipeline/authorships/build_authorships.py`) est idempotent en mode incrémental ; le mode pipeline `full` exécute en plus une purge complète + rebuild from scratch (TRUNCATE + reset des FK), pour garantir la convergence absolue à intervalle mensuel. Aucun état natif sur la table : le rejet manuel d'une paire (« cette personne n'est pas l'auteur ») vit dans le store `rejected_authorships`, lu en anti-join par les sites de création pour ne jamais recréer la paire.

### Décisions humaines

Deux stores portent les arbitrages saisis à la main, et survivent aux reconstructions de la table dérivée :

- **`rejected_authorships`** — paires (publication, personne) écartées. Clé primaire `(publication_id, person_id)`.
- **`confirmed_authorships`** — signatures épinglées sur une personne. Clé primaire `source_authorship_id`.

## Tables sources

Toutes les sources partagent les mêmes tables, discriminées par la colonne `source` (enum `source_type` : hal, openalex, wos, scanr, theses, crossref, datacite).

- **`source_publications`** : un enregistrement par document par source. Relié à `publications` via `publication_id` (peut être NULL si pas encore rattaché). Contient les métadonnées (doc_type non mappé, oa_status, abstract, keywords, topics, biblio, meta).
- **`source_authorships`** : une signature — un auteur sur un document source. `person_id` et `authorship_id` la relient à la personne et à l'authorship canoniques. Son identité d'auteur — nom normalisé et identifiants — vit sur `author_identifying_keys`, référencée par `identity_id` et partagée par toutes les signatures de même identité. Ses adresses passent par `source_authorship_addresses`, d'où la matview `source_authorship_structures` dérive ses structures.
- **`source_authorship_addresses`** : table de liaison `source_authorships ↔ addresses`. Permet aux normalizers de partager une même chaîne d'adresse normalisée (`addresses.raw_text` → `addresses.normalized_text`) entre plusieurs authorships, et alimente la résolution structure ↔ adresse de la phase `affiliations`.

## `staging` — ingestion par source

Table d'ingestion par source. Cycle de vie en 3 états explicites :

| État | `processed` | `not_found_at` | `raw_data` | Inséré par |
|---|---|---|---|---|
| **À traiter** | FALSE | NULL | plein (payload source) | extracteurs sources |
| **Normalisée** | TRUE | NULL | `{}` (vidé) | normalizers après traitement |
| **Non trouvée** | TRUE | timestamp | `{}` (jamais peuplé) | `fetch_missing_hal` (hal-id ou NNT introuvable) |

Transitions valides :

- `[INSERT extracteur]` → **À traiter** → (`normalize`) → **Normalisée**
- `[INSERT fetch_missing_hal]` → **Non trouvée**

`not_found_at` ne porte que les échecs du cross-import HAL, identifiés par hal-id ou NNT. L'échec n'est pas définitif : HAL peut publier le document plus tard, et sa réapparition efface le marqueur. Les échecs par DOI, eux, vivent tous dans `doi_lookups` (cf. ci-dessous).

`raw_data` vidé après normalisation pour libérer l'espace TOAST. `last_seen_at` est mis à jour à chaque fois qu'un doc est re-vu (extraction bulk ou refetch).

`disappeared_at` marque une ligne dont la source ne renvoie plus le document. À chaque exécution, la phase `refresh_stale` réinterroge les lignes vues pour la dernière fois il y a plus de 90 jours (`STALE_REFRESH_AFTER_DAYS`) ; une absence confirmée pose `disappeared_at`. Le marquage reste sans conséquence : ni exclusion, ni suppression, ni propagation.

CHECK SQL `staging_not_found_at_implies_processed` : `not_found_at IS NULL OR processed`. Verrouille la transition impossible « non trouvée à re-traiter ». Les autres invariants (corrélation `processed` ↔ `raw_data` vidé) ne sont pas verrouillés en SQL — laissés en discipline pour ne pas bloquer les évolutions futures.

## `doi_lookups` — temporisation des échecs de cross-import

Cache des tentatives négatives de cross-import par DOI, pour toutes les sources : `doi_lookups (source, doi, not_found_at, next_retry)`. Un DOI absent d'une source dont il n'est pas l'identifiant natif (hal, openalex, wos, scanr) n'y est pas définitivement absent — elle peut l'indexer plus tard — et l'échec reçoit `next_retry = now() + 30 jours` (`DOI_LOOKUP_RETRY_DAYS`). Chez Crossref et DataCite, dont le DOI est l'identifiant natif, l'échec est définitif et `next_retry` reste NULL.

`get_cross_import_dois` écarte les deux cas — délai non écoulé ou échec définitif — ce qui borne le pool de re-tentatives : sans lui, ces DOI seraient réinterrogés à chaque exécution. Ce ne sont pas des `staging` : pas de payload, pas de cycle de normalisation.

## Propriété des tables

La colonne **Autorité** dit qui a le dernier mot sur le contenu de la table :

- **admin** — saisi depuis l'interface d'administration ; le pipeline ne l'écrase jamais
- **pipeline** — recalculé à chaque exécution
- **mixte** — l'un ou l'autre selon la colonne

| Table | Autorité | Écrit par |
|---|---|---|
| `staging` | pipeline | extracteurs (`infrastructure/sources/*/extract_*.py`, cross-imports) |
| `doi_lookups` | pipeline | cross-imports DOI (`infrastructure/sources/*/fetch_missing_doi.py`) |
| `source_publications` | pipeline | `application/pipeline/normalize/normalize_*.py` |
| `author_identifying_keys` | pipeline | `normalize_*.py` (via `_authorships_batch.py`) |
| `source_authorships` | mixte | `normalize_*.py` (pipeline) ; `in_perimeter` par la phase `affiliations`, `authorship_id` par la phase `authorships` ; `person_id` par le pipeline ou en admin (orphan-assign) |
| `source_authorship_addresses` | pipeline | `normalize_*.py` (via `_authorships_batch.py`) |
| `authorships` | pipeline | `build_authorships.py` (dédupliquée, dérivée des sources) |
| `rejected_authorships` | admin | `application/services/authorships/core.py` |
| `confirmed_authorships` | admin | `application/services/authorships/assign_orphans.py` |
