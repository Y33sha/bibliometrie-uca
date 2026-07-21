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

## Phasage

### Audit

- [ ] Recenser tous les vocabulaires fermés du domaine et leur forme (StrEnum / Literal / chaînes), avec leurs collections parallèles.
- [ ] Cartographier les usages de chacun (domaine, infrastructure SQL, interfaces, sérialisation frontend) pour dimensionner chaque migration.
- [ ] Confirmer la correspondance exacte membres ↔ libellés des enums PostgreSQL (un écart casserait comparaisons et casts).

### doc_type (pilote)

- [ ] `DocType` Literal → StrEnum ; `DOC_TYPES` et `DOC_TYPES_SET` dérivés de l'enum.
- [ ] Remplacer les chaînes doc_type en dur du DSL `_RULES` et de `resolve_cluster_doi_corrections` par des membres (ou une constante référençable pour la famille ouvrage).
- [ ] `fetch_doi_cluster_candidates` : `'book'` / `'book_chapter'` / `'dataset'` → membres.

### source / oa_status / journal_type / oa_model

- [ ] `source` (chaînes + `ALL_SOURCES` + `SOURCE_PRIORITY`) → StrEnum ; collections dérivées.
- [ ] `oa_status` (chaînes + `OA_RANK` + `OA_STATUSES` + `_KNOWN_OA_STATUSES`) → StrEnum ; fusionner les deux listes.
- [ ] `journal_type` et `oa_model` Literal → StrEnum.

### Exploitation en SQL

- [ ] Balayer les requêtes pour remplacer les littéraux de ces vocabulaires par `<Enum>.<X>.value`.
- [ ] `metadata_correction` : remonter le mapping `relation_type` DataCite → `DoiClusterCase` au domaine.

## Sites recensés

Littéraux de vocabulaires fermés repérés dans le SQL, à remplacer par des membres d'enum (liste tenue au fil des relectures) :

- [ ] `infrastructure/queries/pipeline/metadata_correction.py` — `'book'`, `'book_chapter'`, `'dataset'`, `'datacite'` ; et le mapping `relation_type` DataCite → `DoiClusterCase` du `CASE`.
- [ ] `infrastructure/queries/pipeline/oa_status.py` — `'green'` (statut OA du dépôt en archive ouverte).

## Questions ouvertes

- **Frontière base.** Rester sur l'égalité `str` de StrEnum (donnée = `str`, littéraux = membres), ou convertir en membres à l'ingestion pour un typage strict ? La première voie est la moins coûteuse et suffit aux comparaisons.
- **relation_type DataCite.** C'est du vocabulaire externe (schéma DataCite), pas une colonne du projet. Le mapping vers `DoiClusterCase` est métier et doit remonter au domaine ; ses clés (`IsVersionOf`…) restent-elles des chaînes DataCite ou deviennent-elles un StrEnum interne ?
- **Périmètre.** S'arrêter aux vocabulaires adossés à un enum PostgreSQL, ou inclure les vocabulaires purement applicatifs (codes ISO pays, `kind` de `place_name_forms`) ?
- **Articulation avec l'archivé `METIER_doc-types`.** Ce chantier ne touche que la représentation (Literal → StrEnum), pas la taxonomie des types ni les règles de mapping des sources, déjà traitées.
