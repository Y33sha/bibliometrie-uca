# Chantier — Pureté du domaine

Commencé et terminé le 2026-05-12.

## Contexte

Découverte en cours du chantier `chasse-aux-any` (tranche normalize JSONB) : `domain/` n'est pas pur. Trois fichiers importent `pydantic` pour modéliser des colonnes JSONB qui sont en réalité de l'I/O, pas du métier.

```
domain/structure.py:17:        from pydantic import BaseModel, ConfigDict, field_validator
domain/persons/source_ids.py:12: from pydantic import BaseModel, ConfigDict, field_validator
domain/publication.py:28:        from pydantic import BaseModel, ConfigDict, field_validator
```

Aucun contrat `import-linter` n'enforçait cette pureté : le contrat `type = "layers"` régule uniquement l'ordre entre les 4 couches DDD (`interfaces > [infrastructure | application] > domain`). Aucune règle n'interdit les libs externes (`pydantic`, `sqlalchemy`, `fastapi`, `starlette`, `psycopg`) dans `domain/`.

Bonne nouvelle : seul `pydantic` contamine actuellement (vérifié par grep). Pas de `sqlalchemy`, pas de `fastapi`, pas de `psycopg`.

## Constat — ce qui n'est pas du métier dans `domain/`

10 `BaseModel` qui sont tous des **modèles d'I/O JSONB** :

| Modèle | Fichier | Rôle |
|---|---|---|
| `StructureApiIds` | `domain/structure.py` | Colonne `structures.api_ids` |
| `PersonSourceIds` | `domain/persons/source_ids.py` | Colonne `source_persons.source_ids` |
| `ExternalIds` | `domain/publication.py` | Colonne `source_publications.external_ids` |
| `PublicationBiblio` | `domain/publication.py` | Colonne `*.biblio` |
| `EcoleDoctorale` | `domain/publication.py` | Sous-modèle `meta.ecoles_doctorales` |
| `Partenaire` | `domain/publication.py` | Sous-modèle `meta.partenaires` |
| `PublicationMeta` | `domain/publication.py` | Colonne `*.meta` (thèses) |
| `OpenAlexTopic` | `domain/publication.py` | Sous-modèle `topics.openalex` |
| `ThesesTopics` | `domain/publication.py` | Sous-modèle `topics.theses` |
| `PublicationTopics` | `domain/publication.py` | Colonne `*.topics` |

Ces classes valident la forme d'un dict et le sérialisent — ce n'est pas du comportement métier.

## Référence — Cosmic Python

Trois principes pertinents :

1. **Le domaine ne dépend de rien.** Pas de SQLAlchemy, pas de Pydantic, pas de framework. Critère empirique : si on supprime toutes les libs tierces du projet, `domain/` doit encore se charger et ses tests passer.
2. **Pas d'anaemic domain model.** Le domaine porte le **comportement métier** (règles, invariants, transitions d'état), pas seulement des structures de données. Un `BaseModel` qui ne fait que valider un dict est par définition de l'I/O — sa place est ailleurs.
3. **Schemas Pydantic = anti-corruption layer côté adapter.** Pydantic valide à la frontière entre le monde extérieur (HTTP request, payload API, ligne DB) et le domaine. Sa place naturelle est dans les `infrastructure/` (adapters) et `interfaces/` (entrypoints), jamais au cœur.

## Décisions

1. **Cible architecturale** : les 10 `BaseModel` vivront dans `infrastructure/db/jsonb_models/` (cohérent : ils décrivent les colonnes JSONB de la base, c'est un détail de l'adapter DB).
2. **Pas de duplication source/DB pour cette première passe.** Si plus tard on dédouble les schemas (un côté source HAL pour parser le payload, un côté DB pour stocker), ce sera un chantier de suite. Aujourd'hui un même `ExternalIds` couvre les deux usages.
3. **Les normalizers (couche `application`) manipulent des `dict` / `JsonValue`** quand ils construisent ces payloads, pas des `BaseModel`. La validation pydantic se fait à l'entrée du query service (`infrastructure`). Cohérent avec la règle layered (`application → infrastructure` interdit) : le caller passe un dict, l'adapter le valide en interne.
4. **Garde-fou import-linter** ajouté pour interdire pydantic + sqlalchemy + fastapi + starlette + psycopg dans `domain.*`.

## Phasage

### Phase 1 — Inventaire fin et règles métier latentes

- [x] Classification symbole par symbole des 3 fichiers `domain/`
  contenant du pydantic. Résultat : les 10 `BaseModel` sont tous
  de l'I/O JSONB sans comportement métier. Aucun ne dépasse le
  rôle « valider la forme d'un dict + sérialiser ».
- [x] Identification des règles latentes :
  - `hal_person_id ≤ 0 = sentinelle` : faux problème, **déjà**
    code testable dans `domain/persons/creation.py:should_create_source_person`.
  - `meta.discipline` canonique vs `topics.theses.discipline` :
    pas une règle, c'est un cleanup TODO (renvoyé à un chantier
    dédié).
  - Enums `SourceCode` / `PersonSourceIdentifierType` : vraies
    absences, mais relèvent de l'émergence de domaine →
    `richesse-domain`, pas `purete-domain`.
- [x] Constat surprenant : les 10 `BaseModel` sont quasi-inutilisés
  en runtime — seul caller prod = `application/structures.py`.
  Le reste est documentaire (uniquement des tests). La validation
  Pydantic n'a jamais lieu dans le pipeline. → simplifie le
  déplacement.

### Phase 2 — Déplacer les `BaseModel` vers `infrastructure/db/jsonb_models/`

Décisions actées :
- **A1** : cible = `infrastructure/db/jsonb_models/` (sous-package
  avec 3 fichiers miroirs des 3 fichiers `domain/` d'origine).
- **C2** : tout déplacé en un seul commit (volume mécanique).
- **D1** : pour `application/structures.py` (seul caller prod),
  la validation Pydantic descend dans le repository
  (`infrastructure/repositories/structure_repository.py`). Le
  service passe le `dict` brut au repo ; le repo valide à
  l'entrée de `create_structure` / `update_structure_fields` et
  traduit `pydantic.ValidationError` → `domain.errors.ValidationError`.

- [x] `infrastructure/db/jsonb_models/__init__.py` + `structure.py`
  + `persons.py` + `publication.py` créés (10 `BaseModel`).
- [x] `domain/structure.py` réduit à un docstring d'amorce.
- [x] `domain/persons/source_ids.py` supprimé.
- [x] `domain/publication.py` allégé : 8 `BaseModel` retirés,
  import pydantic retiré.
- [x] Refactor structure (D1) :
  - `application/structures.py` : `_validate_api_ids` supprimé,
    plus d'import `pydantic`/`StructureApiIds`, dict brut passé
    au repo.
  - `infrastructure/repositories/structure_repository.py` : helper
    `_normalize_api_ids` ajouté, appelé dans `create_structure` et
    `update_structure_fields` (intercepte `fields["api_ids"]`).
- [x] Tests déplacés :
  - `tests/unit/domain/test_structure.py` (supprimé) → `tests/unit/infrastructure/db/jsonb_models/test_structure.py`.
  - `tests/unit/domain/persons/test_source_ids.py` (supprimé) → `tests/unit/infrastructure/db/jsonb_models/test_persons.py`.
  - 4 classes (`TestExternalIdsParsing`, `TestPublicationBiblio`,
    `TestPublicationMeta`, `TestPublicationTopics`) extraites de
    `tests/unit/domain/test_publication.py` vers
    `tests/unit/infrastructure/db/jsonb_models/test_publication.py`.
  - `__init__.py` ajouté dans `tests/unit/infrastructure/db/jsonb_models/`
    pour résoudre la collision pytest de basename avec
    `tests/unit/domain/test_publication.py`.

### Phase 3 — Garde-fou import-linter

- [x] Contrat `forbidden` ajouté dans `pyproject.toml` :
  ```toml
  [[tool.importlinter.contracts]]
  name = "Domain : pas de framework externe"
  type = "forbidden"
  source_modules = ["domain"]
  forbidden_modules = ["pydantic", "sqlalchemy", "fastapi", "starlette", "psycopg"]
  ```
- [x] `include_external_packages = true` activé au niveau
  `[tool.importlinter]` (pré-requis pour les contrats forbidden
  ciblant des modules externes).
- [x] Le contrat passe en vert.

### Phase 4 — Validation

- [x] `uv run mypy .` : 290 fichiers, no issues.
- [x] `uv run pytest tests/unit/` : 577 tests verts.
- [x] `uv run lint-imports` : 3 contrats verts (Couches DDD,
  Routers, Domain pas de framework externe).
- [x] `uv run ruff check .` : clean.

## Hors scope (chantiers de suite)

- **Richesse du domaine** — chantier dédié à créer. Aujourd'hui le
  domaine contient des VOs (DOI, HALId, NNT, ORCID, IdHAL, IdRef),
  des règles isolées (`resolve_doi_conflict`, `best_oa_status`,
  `names_compatible`) et des dataclasses de résultat (PubByDoi,
  PubByNnt, …). Pas d'entités au sens DDD : pas de `Publication`
  avec identité + comportement, pas de `Person`, pas de `Structure`.
  Le code applicatif manipule des `dict` que les query services
  renvoient — c'est le pattern « anaemic domain model » que
  Cosmic Python combat. Candidats d'aggregates : `Publication`
  (root) + Authorships + SourcePublications + identifiants ;
  `Person` (root) + PersonRH + PersonIdentifiers + PersonNameForms ;
  `Structure` (root) + StructureNameForms + StructureRelations +
  ApiIds. Avec méthodes qui forcent les invariants (`Person.merge_with`
  bloque si les deux ont un `persons_rh`, etc.).
- **Dédoublement des schemas source vs DB** : un schema Pydantic
  côté source (`infrastructure/sources/<source>/schemas.py`) qui
  parse le payload brut de l'API, un schema côté DB qui valide
  l'écriture JSONB. Pertinent si les formats divergent.

## Questions ouvertes

- **Où placer les helpers de décodage HTML** (`clean_publication_title`,
  `_decode_html_entities_once`) ? Frontière entre I/O et règle de
  canonicalisation métier. Probablement à laisser dans `domain/` :
  c'est une règle « tout titre canonique est décodé », pas un détail
  d'adapter.
- **Les dataclasses de résultat de requête** (`PubByDoi`, `PubByNnt`,
  `PubByTitle`, `PubThesisCandidate`) — à garder dans `domain/` ou
  déplacer côté ports/repository ? Pour l'instant elles vivent dans
  `domain/publication.py`. Cosmic Python recommanderait probablement
  de les laisser là (ce sont des DTOs domain de lecture), tant qu'on
  ne les confond pas avec les entités à venir.
