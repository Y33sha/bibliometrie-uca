# Domain — noyau métier pur

*À jour le 2026-06-30.*

Contenu, organisé par concept métier :

- **Agrégats** (entités avec identité + comportement, invariants métier) :
  - `Publication` (+ entité fille `Authorship`) — `domain/publications/`
  - `Person` — `domain/persons/`
  - `PersonIdentifier` (agrégat séparé, identité naturelle `(id_type, id_value)`) — `domain/persons/`
  - `Structure` — `domain/structures/`
  - `Journal` — `domain/journals/`
  - `Publisher` — `domain/publishers/`
  - `Perimeter` — `domain/perimeters/`
- **Value objects** (immuables, identité par contenu) :
  - Identifiants publication : `DOI`, `HALId`, `NNT` (`domain/publications/identifiers.py`)
  - Identifiants personne : `ORCID`, `IdHAL`, `IdRef` (`domain/persons/identifiers.py`)
  - Identifiants structure : `RorId`, `HalCollection` (`domain/structures/identifiers.py`)
  - Formes de nom : `PersonNameForm`, `StructureNameForm`
  - Adresse : `Address` (défini par `normalized_text`)
  - Enums : `StructureType`, `AttributionStatus` (statut d'un `PersonIdentifier`)
- **Règles métier pures** : matching de personnes (`domain/persons/matching.py`), invariant de fusion de personnes (`Person.can_merge_with` dans `domain/persons/person.py`), déduplication des publications par clustering en composantes connexes (primitive pure `domain/entity_resolution.py`, plan de réconciliation `domain/publications/reconciliation.py`) et agrégation cross-source des métadonnées (`domain/publications/aggregation.py`), validation des relations structure (`domain/structures/relations.py`), `doc_types`, `authorship_roles`, `sources` (référentiel des 6 sources).

Le domaine est testé en unit sans DB. Il ne contient aucun port — les Protocols de persistance vivent dans `application/ports/repositories/`.

## Conventions d'hydratation des agrégats

- Chaque repository d'agrégat expose `find_by_id(id) -> Entity | None` qui charge l'*aggregate root*. Pour les agrégats riches (`Publication`, `Person`, `Structure`), les VOs internes (name forms, identifiers) sont chargés avec le root quand ils sont peu coûteux ; les entités filles (ex. `Authorship` de `Publication`) ne sont pas chargées par défaut (composition lazy — méthode dédiée `find_by_publication_id` sur `AuthorshipRepository`).
- Les références entre agrégats sont **par id** (pattern Cosmic Python ch. 7), pas par objet : `Authorship.person_id`, `Journal.publisher_id`, `Perimeter.structure_ids` — pas d'hydratation transitive.
- Le mapping `row SQL → entité` vit côté infra dans une **fonction libre `_<entity>_from_row(row) → Entity`** au sein du module repo (`infrastructure/repositories/*.py`). Pas de classmethod sur l'entité (le domain ne dépend pas de SQLAlchemy) ; pas de classe mapper dédiée (overkill).
