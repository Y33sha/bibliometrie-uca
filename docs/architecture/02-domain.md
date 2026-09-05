# Domain — noyau métier pur

*À jour le 2026-09-05.*

- **Agrégats** (entités avec identité + comportement, invariants métier) :
  - `Publication` — `domain/publications/` : agrégation entre sources (`aggregation.py`), plan de réconciliation (`reconciliation.py`), règles sur les métadonnées (`metadata.py`), types de document et périmètre documentaire (`doc_types.py`, `scope.py`), rôles auteur (`authorship_roles.py`), vocabulaire des relations entre publications (`relations.py`)
  - `SourcePublication` (image d'un document dans une source, en lecture seule) — `domain/source_publications/` : clés de confirmation du dédoublonnage (`keys.py`), correction des métadonnées (`metadata_correction/`), correspondance des nomenclatures de type de document (`doc_types.py`), conservation des valeurs d'origine (`raw_metadata.py`)
  - `Person` — `domain/persons/` : décision de rapprochement (`matching.py`), comparaison et analyse des noms (`name_matching.py`), politique de création (`creation.py`), invariant de fusion (`Person.can_merge_with`)
  - `PersonIdentifier` (agrégat séparé, identité naturelle `(id_type, id_value)`) — `domain/persons/`
  - `Structure` — `domain/structures/` : relations entre structures — types admis, refus de l'auto-référence et des cycles (`relations.py`)
  - `Journal` — `domain/journals/` : types de publication attendus en fonction du `journal_type` (`expected.py`)
  - `Publisher` — `domain/publishers/`
  - `Perimeter` — `domain/perimeters/`
- **Value objects** (immuables, identité par contenu) :
  - Identifiants publication : `DOI`, `HALId`, `NNT`, `PMID`, `PMCID`, `ArxivId` (`domain/publications/identifiers.py`)
  - Identifiants personne : `ORCID`, `IdHAL`, `IdRef`, `HalPersonId` (`domain/persons/identifiers.py`)
  - Identifiants structure : `RorId`, `HalCollection` (`domain/structures/identifiers.py`)
  - Formes de nom : `PersonNameForm`, `StructureNameForm`
  - Enums : `StructureType`, `AttributionStatus` (statut d'un `PersonIdentifier`)
- **Utilitaires partagés** :
  - `entity_resolution.py` — regroupement en composantes connexes, primitive du dédoublonnage
  - `sources/` — référentiel des 7 sources
  - `normalize.py`, `dates.py` — normalisation des textes et des dates
  - `countries.py` — règles sur les pays des publications
  - `stats.py` — vocabulaire des dimensions et des mesures du pivot
  - `urls.py` — comparaison d'une URL à un domaine, par son hôte
  - `config.py` — confidentialité des paramètres applicatifs
  - `errors.py` — exceptions métier
  - `types.py` — lecture des données JSON

## Conventions d'hydratation des agrégats

- Chaque repository d'agrégat expose `find_by_id(id) -> Entity | None` qui charge l'*aggregate root*. Pour les agrégats riches (`Publication`, `Person`, `Structure`), les value objects internes — formes de nom, identifiants — sont chargés avec lui.
- Les références entre agrégats sont **par id**, pas par objet : `Authorship.person_id`, `Journal.publisher_id`, `Perimeter.root_structure_ids` — pas d'hydratation transitive.
- Le mapping `row SQL → entité` vit côté infrastructure dans une fonction libre `_<entity>_from_row(row) -> Entity`, au sein du module du repository (`infrastructure/repositories/*.py`).
