# Vocabulaires fermés : StrEnum plutôt que Literal / chaînes nues

## Contexte

Le domaine mélange deux représentations pour ses vocabulaires fermés — les valeurs des colonnes d'enum PostgreSQL :

- **StrEnum** — référençable, itérable, une seule définition : `RelationType`, `DoiClusterCase`, `MetadataCorrectionRule`, `AttributionStatus`, `StructureType`. Plusieurs correspondent à des colonnes d'enum PostgreSQL (`publication_relations.relation_type`, `structures.structure_type`, `person_identifiers.status`).
- **`Literal` ou chaînes nues** — non référençables, doublées de collections parallèles : `doc_type` (`DocType` Literal + `DOC_TYPES` tuple + `DOC_TYPES_SET`), `journal_type` et `oa_model` (Literal + tuples dérivés), `source` (chaînes + `ALL_SOURCES` + `ALL_SOURCES_SET` + `SOURCE_PRIORITY`), `oa_status` (chaînes + `OA_RANK` + `OA_STATUSES`, plus un `_KNOWN_OA_STATUSES` séparé dans le parseur OpenAlex).

Ces quatre-là (`doc_type`, `source`, `oa_status`, `journal_type`) sont pourtant aussi des colonnes d'enum PostgreSQL, exactement comme `structure_type` ou `relation_type`. La distinction StrEnum vs Literal ne suit donc aucun principe : c'est de l'accrétion.

Coûts concrets :

- **Constantes magiques en SQL.** Une requête ne peut pas référencer un `Literal`. `infrastructure/queries/pipeline/metadata_correction.py:fetch_doi_cluster_candidates` réécrit `'book'`, `'book_chapter'`, `'dataset'`, `'datacite'` en dur, et encode même le mapping `relation_type` DataCite → `DoiClusterCase` dans un `CASE` — du savoir métier en infrastructure. La même requête source pourtant proprement ses valeurs de sortie via `DoiClusterCase.<X>.value` : le bon patron existe déjà, appliqué à moitié.
- **Collections parallèles qui dérivent.** `oa_status` porte `OA_STATUSES` (dans `metadata`) et `_KNOWN_OA_STATUSES` (dans `sources/openalex`) : deux listes du même vocabulaire, à tenir synchrones à la main. Un StrEnum les remplace par `frozenset(OaStatus)`. Même schéma pour `doc_type` (Literal + tuple + set) et `source` (trois collections).
- **Chaînes en dur disséminées.** Les doc_types apparaissent en clair dans le DSL de correction (`_RULES`), l'agrégation, le SQL et le mapping des nomenclatures sources — sans point unique référençable, donc sans garde contre une faute de frappe silencieuse.

## Décisions

- Adopter **StrEnum** pour les vocabulaires fermés adossés à un enum PostgreSQL : `doc_type`, `source`, `oa_status`, `journal_type`, `oa_model`. Les membres portent exactement les libellés de l'enum PostgreSQL — StrEnum héritant de `str`, `Member == "libellé"` reste vrai, et les comparaisons existantes tiennent.
- Les ensembles dérivés (`DOC_TYPES_SET`, `ALL_SOURCES_SET`, `OA_STATUSES`, `_KNOWN_OA_STATUSES`) se dérivent de l'enum (`frozenset(DocType)`), sans liste parallèle. Les ordonnancements (`SOURCE_PRIORITY`, `OA_RANK`) restent des structures à part, mais leurs clés référencent les membres.
- Le SQL référence les membres (`DocType.BOOK.value`, `Source.DATACITE.value`), comme le fait déjà `DoiClusterCase`. Le mapping `relation_type` DataCite → `DoiClusterCase` remonte au domaine (un dict), le SQL le consomme.
- Frontière base : psycopg rend des `str` nues, pas des membres d'enum. On s'appuie sur l'égalité `str` de StrEnum — pas de conversion imposée à l'ingestion — sauf si l'audit révèle un point qui exige des membres stricts.
- Le traitement s'étend aux vocabulaires fermés qui ne sont pas des enums PostgreSQL mais des clés JSONB : les clés de confirmation (`hal_id`, `arxiv_id`, `pmid`, `nnt`) reçoivent une définition unique côté domaine, référencée par les requêtes qui les énumèrent.

## Phasage

### Audit

- [x] Recenser tous les vocabulaires fermés du domaine et leur forme (StrEnum / Literal / chaînes), avec leurs collections parallèles.
- [x] Cartographier les usages de chacun (domaine, infrastructure SQL, interfaces, sérialisation frontend) pour dimensionner chaque migration.
- [x] Confirmer la correspondance exacte membres ↔ libellés des enums PostgreSQL (comparaisons et casts couverts par la suite d'intégration).

### doc_type (pilote)

- [x] `DocType` Literal → StrEnum ; `DOC_TYPES` et `DOC_TYPES_SET` dérivés de l'enum ; `ARTICLE_SUBTYPES` et `DOC_TYPE_FAMILIES` référencent les membres. `pivot.py` SQL-quotait via `repr` (cassé par le StrEnum), corrigé vers `.value`.
- [x] Chaînes doc_type du DSL `_RULES` et de `resolve_cluster_doi_corrections` → membres `DocType` ; la whitelist récurrente `{article, other}` (7×) repliée sur la constante `_ARTICLE_OR_OTHER`.
- [x] `fetch_doi_cluster_candidates` : `'book'` / `'book_chapter'` / `'dataset'` → `{DocType.X.value}` (SQL déjà en f-string, patron `DoiClusterCase`).

### source / oa_status / journal_type / oa_model

- [x] `source` → StrEnum `Source` ; `ALL_SOURCES`, `SOURCE_PRIORITY`, `DOI_SEARCHABLE_SOURCES`, `STRUCTURE_API_SOURCES` et leurs sets dérivés des membres. Les helpers SQL (`sources_sql.py`) interpolent déjà via `f"'{s}'"`, intacts. Le remplacement des littéraux `"hal"`… épars (Python et SQL) relève de l'exploitation aval.
- [x] `oa_status` → StrEnum `OaStatus` (dans `metadata.py`). `OA_RANK` garde des clés-membres (annoté `dict[str, int]` pour que `best_oa_status.get(str)` tienne), `OA_STATUSES` et `ACCESS_LEVELS` dérivés des membres, `OA_STATUS_UNKNOWN_DEFAULT` = membre. `_KNOWN_OA_STATUSES` (OpenAlex) référence les membres : c'est un sous-ensemble curé (6 statuts, sans unknown/embargoed), **pas** un doublon d'`OA_STATUSES` (8) — donc pas de fusion, contrairement à ce que supposait le contexte.
- [x] `journal_type` et `oa_model` Literal → StrEnum ; collections et labels FR dérivés des membres. Consommateurs Python alignés (normalize, enrich OpenAlex, règles de correction, hydratation `Journal`) ; mypy vert. La phase d'exploitation SQL reste à part.

### persons (resolution_mode, id_type)

- [x] `resolution_mode` Literal → StrEnum `ResolutionMode` (`domain/persons/matching.py`) ; `RESOLUTION_MODE_BY_REASON` mappe vers des membres, `tables.py` déballe l'enum (`*ResolutionMode`) au lieu de `get_args`.
- [x] `id_type` chaînes → StrEnum `PersonIdentifierType` (`domain/persons/identifiers.py`) ; `PERSON_IDENTIFIER_TYPES` = `tuple(PersonIdentifierType)`, `PUBLIC_PERSON_IDENTIFIER_TYPES` = sous-ensemble de membres, dispatch `_IDENTIFIER_VALUE_OBJECTS` keyé par membres. Les littéraux `id_type` disséminés en SQL (filtres de lecture, matching) relèvent de l'exploitation aval.

### Exploitation en SQL

Principe (pipeline comme couche lecture API) : un **prédicat** sur une valeur devient `<Enum>.<X>.value` interpolé ; une **énumération multi-valeurs** (une colonne ou une branche par membre) est **générée** depuis l'enum, sans liste manuelle parallèle.

- [ ] Balayer les requêtes pour remplacer les littéraux de ces vocabulaires par des membres d'enum.
- [x] `metadata_correction` : le mapping `relation_type` DataCite → `DoiClusterCase` vit au domaine (`DATACITE_DIRECT_CONVERGENCE` pour les deux relations à convergence directe, `DATACITE_PACKAGE_PIECE_RELATION` pour `IsPartOf`). Le `CASE` et le filtre `IN` de la requête sont générés depuis ce mapping ; les clés DataCite (`IsVersionOf`…) restent des chaînes externes.
- [x] `infrastructure/queries/api/filters.py` (pilote couche lecture) : ventilation OA par statut (`OA_BREAKDOWN_COLS_SQL`) générée depuis `OaStatus` (une colonne par membre) ; buckets du dashboard, prédicats `source = 'hal'`, `structure_type = 'labo'` et statuts d'identifiant/forme de nom → membres inline.
- [x] `infrastructure/queries/api/publications/list.py` : pivot des identifiants source (`_SOURCE_ID_COLUMNS`, cinq sources) généré depuis `Source` et partagé par les deux listes qui l'exposent ; l'export thèses (quatre sources, sans `wos` par contrat) garde son pivot inline ; prédicats `'labo'` et `source = 'hal'` → membres. Les dicts Python de présentation (`_SOURCE_URL`, `_THESES_STATUS_LABELS`) gardent leurs clés-chaînes : lookups à échec bruyant, hors du périmètre SQL.
- [x] `infrastructure/queries/api/publications/detail.py` : flags de présence par source (quatre sources d'authorship, sans theses) inline ; prédicats `source = 'theses'` (×2) et le test Python `doc_type in {thesis, ongoing_thesis}` → membres `Source` / `DocType`.
- [x] `infrastructure/queries/api/publications/facets.py` : prédicats `structure_type = 'labo'` (×2), `source = 'hal'` (×7), `oa_status = 'embargoed'` → membres.
- [x] `infrastructure/queries/api/stats/summary.py` et `stats/pivot.py` : `structure_type = 'labo'` et le `CASE` oa_access (`'embargoed'` / `'closed'`) → membres. `doc_type_grouped_sql` génère déjà son `CASE` depuis `DOC_TYPE_FAMILIES`.
- [x] `infrastructure/queries/api/persons/detail.py` : prédicats source (hal / openalex / wos / theses, en `WHERE` et en `'<source>' AS source`) et `structure_type = 'labo'` → membres `Source` / `StructureType`.
- [x] `infrastructure/queries/api/persons/admin.py` : statuts (`pending` / `confirmed`), marqueur `'persons'` (`CANONICAL_NAME_FORM_SOURCE`), `structure_type = 'labo'` (×2) → membres ; l'array des types d'identifiant du CTE de conflits (`_ID_TYPES_ARRAY_SQL`) généré depuis `PERSON_IDENTIFIER_TYPES`.
- [x] `infrastructure/queries/api/structures.py` : `doc_type = 'article'` (×2) → `DocType.ARTICLE.value` ; `relation_type = 'est_tutelle_de'` → `StructureRelationType.EST_TUTELLE_DE.value`.
- [x] `structure_relations.relation_type` (colonne texte, deux valeurs endogènes `est_tutelle_de` / `est_partenaire_de`) reçoit un StrEnum `StructureRelationType` (`domain/structures/relations.py`), référencé par `structures.py` et `perimeter.py`. La colonne reste `text` (pas d'enum PostgreSQL) et l'écriture n'est pas encore validée contre l'enum — validation à l'écriture laissée hors chantier.
- [x] `place_name_forms.kind` (colonne texte, contrainte `CHECK` à trois valeurs `country` / `institution` / `city`) reçoit un StrEnum `PlaceNameKind` (`domain/countries.py`), référencé par les requêtes de la phase `countries` (`load_country_forms`, `load_place_forms`) et par le `CHECK` de `tables.py`, généré depuis l'enum. Les CLI oneshot de gestion des noms de lieux gardent leurs littéraux (transitoires, hors périmètre maintenu).
- [x] Codes ISO pays : hors périmètre — standard externe (ISO 3166) stocké en `text` (`publications.countries`, `place_name_forms.iso_code`), pas un vocabulaire fermé endogène. Les seules valeurs propres au projet sont les sentinelles `NO_COUNTRY_CODE` (`"xx"`) et `DOMESTIC_COUNTRY_CODE` (`"fr"`), déjà des constantes nommées de `domain/countries.py`.
- [x] CLI `merge_person_duplicates_by_lab.py` et `oneshot/audit_name_pair_overlaps.py` : `structure_type = 'labo'` → `StructureType.LABO.value`.

## Sites recensés

Littéraux de vocabulaires fermés repérés dans le code (SQL du pipeline et ports API), à remplacer par des membres d'enum (liste tenue au fil des relectures) :

- [x] `infrastructure/queries/pipeline/metadata_correction.py` — doc_types (`'book'` / `'book_chapter'` / `'dataset'`) faits en phase pilote, `source = 'datacite'` → `Source.DATACITE.value` (×2), et le mapping `relation_type` DataCite → `DoiClusterCase` remonté au domaine (cf. « Exploitation en SQL »).
- [x] `infrastructure/queries/pipeline/oa_status.py` — `'green'` (dépôt en archive ouverte) et `'unknown'` (défaut du dénombrement) → `OaStatus.<X>.value`.
- [x] `infrastructure/queries/pipeline/relations.py` — `'datacite'` / `'crossref'` → `Source.<X>.value`, `'erratum'` / `'preprint'` / `'dataset'` → `DocType.<X>.value` (prédicats « substantive » distincts entre les deux requêtes, pas de set partagé à remonter).
- [x] Clés de confirmation → StrEnum `ConfirmationKey` (`domain/source_publications/keys.py`), les 4 identifiants `external_ids` uniformément (la nature array de `hal_id` reste un détail de persistance). Les trois sites qui les énumèrent — `keys.py` `tokens()`/projection, `relations.py` `_SHARED_KEY_PAIRS_SQL`, `publications/reconciliation.py` `_UNIVERSE_SQL` — génèrent leurs bras depuis l'enum (plus de littéraux `'hal_id'`…). `arxiv_id` harmonisé : il était clé de réconciliation dans `relations` seulement, il l'est maintenant partout (clustering + univers).
- [x] `infrastructure/queries/pipeline/persons/matching.py` — statuts → `AttributionStatus.<X>.value`, modes de résolution → `ResolutionMode.<X>.value`, types d'identifiant → membres `PersonIdentifierType` (arguments de branche et comparaisons Python). Les trois clés jsonb de projection (`person_identifiers->>'orcid'`…) restent des chaînes : extraction de clé auto-documentée par l'alias voisin, pas un prédicat métier.
- [x] `infrastructure/queries/pipeline/persons/name_forms.py` — statuts → `AttributionStatus.PENDING.value`. Le marqueur `'persons'` reçoit une définition unique côté domaine (`CANONICAL_NAME_FORM_SOURCE` dans `domain/persons/name_forms.py`), référencée par le site d'écriture (`populate_person_name_forms`) et les deux lectures SQL (`name_forms`, `matching`).
- [x] `application/ports/api/persons_queries.py` — les trois DTOs référencent `AttributionStatus` : `PersonIdentifierOut.status` prend l'enum entière (inclut `authenticated`), les deux DTOs de forme de nom gardent la restriction à `pending` / `confirmed` / `rejected` via `Literal[AttributionStatus.PENDING, ...]`.
- [x] `infrastructure/repositories/doi_prefix_repository.py` — les Registration Agencies (`'Crossref'` / `'DataCite'` / `'unknown'`…) **restent des chaînes** : `doi_prefixes.ra` est du texte et le vocabulaire des RA n'est pas borné (traîne mEDRA / JaLC / KISTI…) — un StrEnum fermerait à tort une liste ouverte.
- [x] `'labo'` (`structures.structure_type`) → `StructureType.LABO.value` dans toutes les requêtes API et les deux CLI (détail par fichier sous « Exploitation en SQL »). Le réglage d'affichage `laboratories_display_types` n'est **pas** la définition d'un laboratoire (il ne pilote que la page laboratoires) et n'a pas servi ici. Le `CASE` de tri par type de `structures.py` (`_LIST_ORDER_BY`) était un no-op — les deux consommateurs (page publique labos, page admin) trient par acronyme côté client — et a été retiré plutôt que converti.

## Questions ouvertes

- **Frontière base.** Rester sur l'égalité `str` de StrEnum (donnée = `str`, littéraux = membres), ou convertir en membres à l'ingestion pour un typage strict ? La première voie est la moins coûteuse et suffit aux comparaisons.
- **Articulation avec l'archivé `METIER_doc-types`.** Ce chantier ne touche que la représentation (Literal → StrEnum), pas la taxonomie des types ni les règles de mapping des sources, déjà traitées.
