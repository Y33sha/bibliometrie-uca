# Authorships et tables sources

## `authorships` — table de vérité des contributions

Table de liaison recensant les contributions individuelles aux publications. Chaque entrée référence **1 personne**, **1 publication**, *n* structures (via la table de jointure `authorship_structures`). Construite par `application/pipeline/authorships/build_authorships.py` à partir des *authorships* sources.

**Couverture partielle assumée** : la table ne contient des entrées que pour les signataires ayant une `person_id` (cf. [périmètre des persons](04-personnes.md#périmètre)). Les co-auteurs externes des publications UCA n'apparaissent pas ici ; pour obtenir la liste exhaustive des auteurs d'une publication (incluant les externes), passer par `source_authorships`.

Colonnes notables :

- `person_id`
- `in_perimeter` : TRUE si l'auteur est affilié UCA sur cette publication
- `author_position` : position dans la liste d'auteurs
- `is_corresponding` : auteur correspondant
- `roles` (text[]) : rôles (auteur, directeur, rapporteur — pour theses.fr)
- `excluded` : authorship rejetée manuellement

La table de jointure `authorship_structures (authorship_id, structure_id)` porte les affiliations résolues — FK `ON DELETE CASCADE` des deux côtés, PK composite.

**Cohérence avec les sources** : la table est **dérivée** des `source_authorships` — `in_perimeter`, les liens via `authorship_structures`, `is_corresponding`, `author_position`, `roles` sont des consolidations (union ou priorité par source) des authorships sources. Le build (`application/pipeline/authorships/build_authorships.py`) est idempotent en mode incrémental ; le mode pipeline `full` exécute en plus une purge complète + rebuild from scratch (TRUNCATE + reset des FK), pour garantir la convergence absolue à intervalle mensuel. Le champ `excluded`, lui, est métier natif (rejet manuel via l'admin) et survit au rebuild — le build ne le touche pas.

## Tables sources

Toutes les sources partagent les mêmes tables, discriminées par la colonne `source` (enum `source_type` : hal, openalex, wos, scanr, theses, crossref).

- **`source_publications`** : un enregistrement par document par source. Relié à `publications` via `publication_id` (peut être NULL si pas encore rattaché). Contient les métadonnées (doc_type non mappé, oa_status, abstract, keywords, topics, biblio, meta). Le champ `hal_collections` (text[]) est spécifique à HAL.
- **`source_authorships`** : contribution d'un auteur source à un document source. Porte `person_id` (rattachement à une personne canonique), `authorship_id` (FK vers l'authorship canonique), `in_perimeter`, `source_structures` (ARRAY[TEXT] des IDs natifs des structures côté source : numérique HAL, `I****` OpenAlex, noms d'institutions WoS, etc.), `raw_author_name`, `author_name_normalized`, `person_identifiers` (JSONB : `orcid`, `idhal`, `idref`, `hal_person_id`, `researcher_id`), `countries` (ARRAY[CHAR(2)]), `roles`, `excluded`. Les affiliations canoniques résolues sont reliées via la table de jointure `source_authorship_structures (source_authorship_id, structure_id)` (FK ON DELETE CASCADE des deux côtés, PK composite). Les affiliations textuelles brutes sont reliées via `source_authorship_addresses` → `addresses.raw_text`.
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

`raw_data` vidé après normalisation pour libérer l'espace TOAST (le payload brut sera ré-introduit hors DB par le chantier `DATA_raw-data-store.md`). `last_seen_at` est mis à jour à chaque ré-extraction d'un même doc.

CHECK SQL `staging_not_found_at_implies_processed` : `not_found_at IS NULL OR processed`. Verrouille la transition impossible « non trouvée à re-traiter ». Les autres invariants (corrélation `processed` ↔ `raw_data` vidé) ne sont pas verrouillés en SQL — laissés en discipline pour ne pas bloquer les évolutions futures.

## `doi_lookups` — backoff des miss cross-import

Cache des tentatives négatives de cross-import DOI sur les sources **non natives** (hal, openalex, wos, scanr). Un DOI absent d'une de ces sources n'y est pas définitivement absent (elle peut l'indexer plus tard) : on l'enregistre dans `doi_lookups (source, doi, not_found_at, next_retry)` avec `next_retry = now() + 30 jours` (`DOI_LOOKUP_RETRY_DAYS`). `get_cross_import_dois` exclut les DOI dont `next_retry > now()`, ce qui borne le pool de re-tentatives — sans ce backoff, ces DOI seraient réinterrogés à chaque run (coût API non borné). Ce ne sont pas des `staging` : pas de payload, pas de cycle de normalisation. Le miss Crossref reste, lui, un stub `staging` (source native du DOI, donc définitif).

## Services propriétaires

| Table | Propriétaire | Notes |
|---|---|---|
| `staging` | extracteurs (`infrastructure/sources/*/extract_*.py`, cross-imports) | table unique pour toutes les sources |
| `doi_lookups` | cross-imports DOI (`infrastructure/sources/*/fetch_missing_doi.py`) | backoff des miss sur sources non natives |
| `source_publications` | `application/pipeline/normalize/normalize_*.py` | un fichier par source |
| `source_authorships` | `application/pipeline/normalize/normalize_*.py` | `person_id` écrit par `application/persons.py` et `application/authorships/assign_orphans.py` (rattachement) ; `in_perimeter` et `source_authorship_structures` écrits par `application/pipeline/affiliations/populate_affiliations.py` |
| `source_authorship_addresses` | `application/pipeline/normalize/normalize_*.py` (via `infrastructure.repositories.address_linker.PgAddressLinker`) | — |
| `authorships` | `application/pipeline/authorships/build_authorships.py` + `application/authorships/core.py` + `application/authorships/assign_orphans.py` | dédupliqué (person_id, publication_id), consolide `in_perimeter` et `structure_ids` depuis les sources |
