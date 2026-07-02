# Authorships et tables sources

*À jour le 2026-06-30.*

## `authorships` — table de vérité des contributions

Table de liaison recensant les contributions individuelles aux publications. Chaque entrée référence **1 personne**, **1 publication**, *n* structures (via la matview `authorship_structures`). Construite par `application/pipeline/authorships/build_authorships.py` à partir des *authorships* sources.

**Couverture partielle assumée** : la table ne contient des entrées que pour les signataires ayant une `person_id`. Les co-auteurs externes des publications UCA n'apparaissent pas ici ; pour obtenir la liste exhaustive des auteurs d'une publication (incluant les externes), passer par `source_authorships`.

Colonnes notables :

- `person_id`
- `in_perimeter` : TRUE si l'auteur est affilié UCA sur cette publication
- `author_position` : position dans la liste d'auteurs
- `is_corresponding` : auteur correspondant
- `roles` (text[]) : rôles (auteur, directeur, rapporteur — pour theses.fr)

`authorship_structures (authorship_id, structure_id)` porte les affiliations résolues. C'est une **`MATERIALIZED VIEW`** (pas une table) : union des `source_authorship_structures` des `source_authorships` reliées à l'authorship, rafraîchie (`REFRESH … CONCURRENTLY`) **uniquement par le pipeline** (fin de phase `authorships`). Les actions admin (review adresse↔structure, assign orphelin) recalculent `in_perimeter` en direct mais ne rafraîchissent plus cette matview : l'agrégation des structures dérivées reste sur l'état du dernier run (staleness bornée). Index unique `(authorship_id, structure_id)` + index `(structure_id)` ; pas de FK (le nettoyage d'une authorship supprimée se fait au refresh).

**Cohérence avec les sources** : la table est **entièrement dérivée** des `source_authorships` — `in_perimeter`, les liens via `authorship_structures`, `is_corresponding`, `author_position`, `roles` sont des consolidations (union ou priorité par source) des authorships sources. Le build (`application/pipeline/authorships/build_authorships.py`) est idempotent en mode incrémental ; le mode pipeline `full` exécute en plus une purge complète + rebuild from scratch (TRUNCATE + reset des FK), pour garantir la convergence absolue à intervalle mensuel. Aucun état natif sur la table : le rejet manuel d'une paire (« cette personne n'est pas l'auteur ») vit dans le store `rejected_authorships`, lu en anti-join par les sites de création pour ne jamais recréer la paire.

### `rejected_authorships` — rejets de contributions

Store univoque `(publication_id, person_id, created_at)`, PK composite, FK `ON DELETE CASCADE` vers `publications` et `persons`. Écrit par l'exclusion canonique (croix de la page personne → `PATCH /api/authorships/{id}/exclude`), qui y insère la paire et supprime la row `authorships`. Tous les sites de création d'`authorships` (build + assignation d'orphelins) anti-joignent ce store, de sorte que le rejet survit aux rebuilds — contrairement à un drapeau sur la table dérivée, purgé en mode `full`. Une fusion de personnes transfère les rejets de l'absorbée vers l'absorbante (dédoublonnage sur conflit de PK).

## Tables sources

Toutes les sources partagent les mêmes tables, discriminées par la colonne `source` (enum `source_type` : hal, openalex, wos, scanr, theses, crossref).

- **`source_publications`** : un enregistrement par document par source. Relié à `publications` via `publication_id` (peut être NULL si pas encore rattaché). Contient les métadonnées (doc_type non mappé, oa_status, abstract, keywords, topics, biblio, meta). Le champ `hal_collections` (text[]) est spécifique à HAL.
- **`source_authorships`** : contribution d'un auteur source à un document source. Porte `person_id` (rattachement à une personne canonique), `authorship_id` (FK vers l'authorship canonique), `in_perimeter`, `source_structures` (ARRAY[TEXT] des IDs natifs des structures côté source : numérique HAL, `I****` OpenAlex, noms d'institutions WoS, etc.), `raw_author_name`, `author_name_normalized`, `person_identifiers` (JSONB : `orcid`, `idhal`, `idref`, `hal_person_id`, `researcher_id`), `countries` (ARRAY[CHAR(2)]), `roles`. Les affiliations canoniques résolues sont exposées par la matview `source_authorship_structures (source_authorship_id, structure_id)`, dérivée des `source_authorship_addresses` via les liens `address_structures` confirmés du périmètre actif. Les affiliations textuelles brutes sont reliées via `source_authorship_addresses` → `addresses.raw_text`.
- **`source_authorship_addresses`** : table de liaison `source_authorships ↔ addresses`. Permet aux normalizers de partager une même chaîne d'adresse normalisée (`addresses.raw_text` → `addresses.normalized_text`) entre plusieurs authorships, et alimente la résolution structure ↔ adresse de la phase `affiliations`.

## `staging` — ingestion par source

Table d'ingestion par source. Cycle de vie en 3 états explicites :

| État | `processed` | `not_found_at` | `raw_data` | Inséré par |
|---|---|---|---|---|
| **À traiter** | FALSE | NULL | plein (payload source) | extracteurs sources |
| **Normalisée** | TRUE | NULL | `{}` (vidé) | normalizers après traitement |
| **Non trouvée** | TRUE | timestamp | `{}` (jamais peuplé) | `fetch_missing_hal_id` (hal-id 404), `crossref/fetch_missing_doi` (DOI 404 sur source native) |

Transitions valides :

- `[INSERT extracteur]` → **À traiter** → (`normalize`) → **Normalisée**
- `[INSERT fetch_missing_*]` → **Non trouvée** (état terminal : `not_found_at` posé, jamais re-tenté)

`not_found_at` ne porte que les miss **natifs** — un identifiant natif qui ne résout pas (hal-id 404, DOI 404 chez Crossref), toujours définitif. Les miss **cross-import** (un DOI absent d'une source non native) ne créent pas de row `staging` : ils vont dans `doi_lookups` avec backoff (cf. ci-dessous).

`raw_data` vidé après normalisation pour libérer l'espace TOAST. `last_seen_at` est mis à jour à chaque fois qu'un doc est re-vu (extraction bulk ou refetch).

`disappeared_at` marque une row dont la source ne renvoie plus le document. Posé par la phase `refresh_stale` (à chaque run) : les rows à `last_seen_at` ancien (`> STALE_REFRESH_AFTER_DAYS`, 90 j) sont refetchées par id ; un 404 confirmé → `disappeared_at`, sinon `last_seen_at` est bumpé. Les rows stale **sans DOI** (non refetchables mais re-moissonnées par le bulk) sont marquées directement. Conservateur : on **marque seulement**, aucun effet aval (exclusion / suppression / propagation) pour l'instant.

CHECK SQL `staging_not_found_at_implies_processed` : `not_found_at IS NULL OR processed`. Verrouille la transition impossible « non trouvée à re-traiter ». Les autres invariants (corrélation `processed` ↔ `raw_data` vidé) ne sont pas verrouillés en SQL — laissés en discipline pour ne pas bloquer les évolutions futures.

## `doi_lookups` — backoff des miss cross-import

Cache des tentatives négatives de cross-import DOI sur les sources **non natives** (hal, openalex, wos, scanr). Un DOI absent d'une de ces sources n'y est pas définitivement absent (elle peut l'indexer plus tard) : on l'enregistre dans `doi_lookups (source, doi, not_found_at, next_retry)` avec `next_retry = now() + 30 jours` (`DOI_LOOKUP_RETRY_DAYS`). `get_cross_import_dois` exclut les DOI dont `next_retry > now()`, ce qui borne le pool de re-tentatives — sans ce backoff, ces DOI seraient réinterrogés à chaque run (coût API non borné). Ce ne sont pas des `staging` : pas de payload, pas de cycle de normalisation. Le miss Crossref reste, lui, un stub `staging` (source native du DOI, donc définitif).

## Services propriétaires

**Autorité** : *pipeline* (recalculée à chaque run), *admin* (saisie via l'interface admin, préservée — le pipeline ne l'écrase jamais), *mixte* (selon la colonne), *import* (chargement externe), *référence* (seed).

| Table | Autorité | Écrit par |
|---|---|---|
| `staging` | pipeline | extracteurs (`infrastructure/sources/*/extract_*.py`, cross-imports) |
| `doi_lookups` | pipeline | cross-imports DOI (`infrastructure/sources/*/fetch_missing_doi.py`) |
| `source_publications` | pipeline | `application/pipeline/normalize/normalize_*.py` |
| `source_authorships` | mixte | `normalize_*.py` (pipeline) ; `in_perimeter` par la phase `affiliations`, `authorship_id` par la phase `authorships` ; `person_id` par le pipeline ou en admin (orphan-assign) |
| `source_authorship_addresses` | pipeline | `normalize_*.py` (via `PgAddressLinker`) |
| `authorships` | pipeline | `build_authorships.py` (dédupliquée, dérivée des sources) |
| `rejected_authorships` | admin | exclusion d'une paire (`PATCH /api/authorships/{id}/exclude`) |
