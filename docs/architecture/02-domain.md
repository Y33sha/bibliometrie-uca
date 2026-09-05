# Domain — noyau métier pur

*À jour le 2026-09-05.*

Contenu, organisé par concept métier :

- **Agrégats** (entités avec identité + comportement, invariants métier) :
  - `Publication` (+ entité fille `Authorship`) — `domain/publications/`
  - `SourcePublication` (image d'un document dans une source, en lecture seule) — `domain/source_publications/`
  - `Person` — `domain/persons/`
  - `PersonIdentifier` (agrégat séparé, identité naturelle `(id_type, id_value)`) — `domain/persons/`
  - `Structure` — `domain/structures/`
  - `Journal` — `domain/journals/`
  - `Publisher` — `domain/publishers/`
  - `Perimeter` — `domain/perimeters/`
- **Value objects** (immuables, identité par contenu) :
  - Identifiants publication : `DOI`, `HALId`, `NNT`, `PMID`, `PMCID`, `ArxivId` (`domain/publications/identifiers.py`)
  - Identifiants personne : `ORCID`, `IdHAL`, `IdRef`, `HalPersonId` (`domain/persons/identifiers.py`)
  - Identifiants structure : `RorId`, `HalCollection` (`domain/structures/identifiers.py`)
  - Formes de nom : `PersonNameForm`, `StructureNameForm`
  - Enums : `StructureType`, `AttributionStatus` (statut d'un `PersonIdentifier`)
- **Règles métier pures** : matching de personnes (`domain/persons/matching.py`), invariant de fusion de personnes (`Person.can_merge_with` dans `domain/persons/person.py`), déduplication des publications par clustering en composantes connexes (primitive pure `domain/entity_resolution.py`, plan de réconciliation `domain/publications/reconciliation.py`) et agrégation cross-source des métadonnées (`domain/publications/aggregation.py`), validation des relations structure (`domain/structures/relations.py`), `doc_types`, `authorship_roles`, `sources` (référentiel des 7 sources).
- **Règles sur les images source** (`domain/source_publications/`) : clés de confirmation qui pilotent le dédoublonnage (`keys.py`), correction des métadonnées (`metadata_correction/`), correspondance des nomenclatures de type de document (`doc_types.py`), conservation des valeurs d'origine (`raw_metadata.py`).
- **Transverses** : pays des publications (`countries.py`), registre des dimensions et mesures du pivot (`stats.py`), normalisation des textes et des dates (`normalize.py`, `dates.py`), comparaison d'une URL à un domaine par son hôte (`urls.py`), confidentialité des paramètres applicatifs (`config.py`), exceptions métier (`errors.py`), lecture des données JSON (`types.py`).

Le domaine est testé en unit sans DB.

## Conventions d'hydratation des agrégats

- Chaque repository d'agrégat expose `find_by_id(id) -> Entity | None` qui charge l'*aggregate root*. Pour les agrégats riches (`Publication`, `Person`, `Structure`), les VOs internes (name forms, identifiers) sont chargés avec le root quand ils sont peu coûteux.
- `Authorship` n'est pas hydratée : `AuthorshipRepository` opère en SQL sur la table de liaison — insertion, rattachement des signatures, recalcul des attributs dérivés.
- Les références entre agrégats sont **par id** (pattern Cosmic Python ch. 7), pas par objet : `Authorship.person_id`, `Journal.publisher_id`, `Perimeter.root_structure_ids` — pas d'hydratation transitive.
- Le mapping `row SQL → entité` vit côté infra dans une **fonction libre `_<entity>_from_row(row) → Entity`** au sein du module repo (`infrastructure/repositories/*.py`). Pas de classmethod sur l'entité (le domain ne dépend pas de SQLAlchemy) ; pas de classe mapper dédiée (overkill).
