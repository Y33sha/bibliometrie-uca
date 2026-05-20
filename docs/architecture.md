# Architecture logicielle — Bibliométrie UCA

*Document à jour au 2026-05-20.*

Pour le modèle de données (tables, relations, domaines fonctionnels),
voir [donnees](donnees).

## Vue d'ensemble

Le projet suit une architecture **hexagonale (DDD)**. Le cœur du
système est `application/` (use-cases et orchestrateurs), qui
dépend de `domain/` (noyau pur). Autour de ce cœur, deux bandes
périphériques d'**adapters frères** qui ne se connaissent pas :
`interfaces/` (adapters entrants — HTTP, CLI) et `infrastructure/`
(adapters sortants — DB, APIs externes, logs). La
neutralité entre ces deux bandes repose sur les **ports**
(`Protocol`) définis dans `application/ports/`, qui forment une zone
neutre dont dépendent tous les autres modules.

```
                  ┌─────────────────────────────┐
                  │  domain/                    │
                  │  entités, value objects,    │
                  │  règles métier pures        │  (zéro I/O)
                  └──────────────▲──────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  │  application/               │
                  │  ├─ ports/    (Protocol)    │  ← zone neutre
                  │  └─ use-cases, orchestrateurs
                  └─────▲────────────────▲──────┘
                        │                │
            ┌───────────┘                └──────────────┐
            │                                           │
    ┌───────┴─────────┐                       ┌─────────┴─────────┐
    │  interfaces/    │    ─── ⊥ ───          │  infrastructure/  │
    │  adapters       │   (pas d'import       │  adapters sortants│
    │  entrants :     │   direct l'un de      │  (SQL, APIs       │
    │  routers, CLI   │   l'autre)            │  externes, logs)  │
    └─────────────────┘                       └───────────────────┘
```

**Règles dures.**

1. **Noyau pur.** `domain/` contient zéro I/O, zéro import externe
   hormis `stdlib`. Testable sans DB, sans HTTP, sans mock, en
   millisecondes.

2. **Les ports sont une zone neutre.** `application/ports/*` ne
   contient que des `Protocol`, pas d'implémentation. L'arborescence
   interne (`repositories/` pour les agrégats, `api/` / `pipeline/`
   pour les query services) sert à grouper visuellement, pas à porter
   des règles d'import distinctes.

3. **Use-cases indépendants des adapters sortants.** `application/`
   ne peut pas importer `infrastructure/`. Les services applicatifs
   reçoivent leurs dépendances (repositories, query services) via les
   **ports** (`Protocol`) définis dans `application/ports/` — c'est
   `infrastructure/` qui implémente les ports, pas l'inverse. Contrôlé
   par `import-linter` (contrat `layered` dans `pyproject.toml`).

4. **Routers ⊥ adapters sortants.** Les routers FastAPI
   (`interfaces/api/routers/*`) reçoivent leurs dépendances via
   `Depends(...)` (factories dans `interfaces.api.deps`) ; ils
   n'instancient pas eux-mêmes les `Pg*` concrets. Verrouillé par un
   contrat `import-linter`. Les exceptions assumées (deux modules qui
   importent un utilitaire non-DB) sont déclarées dans le
   `pyproject.toml`, pas ici. Les scripts CLI ne sont pas concernés :
   ils sont leur propre composition root (cf. règle 5).

5. **Le composition root est un endroit précis.** L'instanciation
   concrète des adapters et leur câblage aux use-cases se fait
   dans **un petit ensemble nommé de fichiers** :

   - `interfaces/api/app.py` + `interfaces/api/deps.py` — API HTTP
   - `run_pipeline.py` — pipeline complet
   - `interfaces/cli/pipeline/*` — phases pipeline isolées
   - `interfaces/cli/*` — scripts one-shot

   Ces fichiers sont les **seuls** qui ont légitimement le droit
   d'importer `infrastructure.repositories`, `infrastructure.queries.*`
   ou toute classe `Pg*` concrète. Partout ailleurs, on passe par un
   port.

Le contrat `layers` d'`import-linter` (voir `pyproject.toml`,
section `[tool.importlinter]`) vérifie les règles 1 à 3. Le contrat
`forbidden` "Routers : pas d'import direct de infrastructure"
applique la règle 4. Le contrat `forbidden` "Composition root : Pg*
concrets uniquement dans app et deps" applique la règle 5 pour
`interfaces/api/` (les CLIs restent discipline-only — ils sont leur
propre composition root par nature, cf. règle 5).

## Les 4 couches en détail

### `domain/` — noyau métier pur

Contenu, organisé par concept métier :

- **Agrégats** (entités avec identité + comportement, racines
  d'invariants métier — *aggregate roots* en terminologie DDD) :
  - `Publication` (+ entité fille `Authorship`) — `domain/publications/`
  - `SourcePublication` (+ entité fille `SourceAuthorship`) —
    `domain/source_publications/`
  - `Person` — `domain/persons/`
  - `PersonIdentifier` (agrégat séparé, identité naturelle
    `(id_type, id_value)`) — `domain/persons/`
  - `Structure` — `domain/structures/`
  - `Journal` — `domain/journals/`
  - `Publisher` — `domain/publishers/`
  - `Perimeter` — `domain/perimeters/`
  - `AddressAffiliation` (+ VO interne `StructureLink`) —
    `domain/addresses/`
- **Value objects** (immuables, identité par contenu) :
  - Identifiants publication : `DOI`, `HALId`, `NNT`
    (`domain/publications/identifiers.py`)
  - Identifiants personne : `ORCID`, `IdHAL`, `IdRef`
    (`domain/persons/identifiers.py`)
  - Identifiants structure : `RorId`, `HalCollection`
    (`domain/structures/identifiers.py`)
  - Formes de nom : `PersonNameForm`, `StructureNameForm`
  - Adresse : `Address` (défini par `normalized_text`)
  - Enums : `StructureType`, `AttributionStatus` (statut d'un
    `PersonIdentifier`)
- **Règles métier pures** : matching de personnes
  (`domain/persons/matching.py`), invariant de fusion de personnes
  (`Person.can_merge_with` dans `domain/persons/person.py`),
  déduplication et agrégation cross-source des publications
  (`domain/publications/deduplication.py`, `aggregation.py`, méthode
  `Publication.absorb` dans `domain/publications/publication.py`),
  validation des relations structure (`domain/structures/relations.py`),
  `doc_types`, `authorship_roles`, `sources` (référentiel des 6
  sources).

Le domaine est testé en unit sans DB. Il ne contient aucun port — les
Protocols de persistance vivent dans `application/ports/repositories/`
(cf. section `application/` ci-dessous).

**Conventions d’hydratation des agrégats** :

- Chaque repository d'agrégat expose `find_by_id(id) -> Entity | None`
  qui charge l'*aggregate root*. Pour les agrégats riches
  (`Publication`, `Person`, `Structure`), les VOs internes (name forms,
  identifiers) sont chargés avec le root quand ils sont peu coûteux ;
  les entités filles (ex. `Authorship` de `Publication`) ne sont pas
  chargées par défaut (composition lazy — méthode dédiée
  `find_by_publication_id` sur `AuthorshipRepository`).
- Les références entre agrégats sont **par id** (pattern Cosmic
  Python ch. 7), pas par objet : `Authorship.person_id`,
  `Journal.publisher_id`, `Perimeter.structure_ids` — pas d'hydratation
  transitive.
- Le mapping `row SQL → entité` vit côté infra dans une **fonction libre
  `_<entity>_from_row(row) → Entity`** au sein du module repo
  (`infrastructure/repositories/*.py`). Pas de classmethod sur l'entité
  (le domain ne dépend pas de SQLAlchemy) ; pas de classe mapper
  dédiée (overkill).

#### Où ranger un nouveau port ?

Tous les ports vivent dans `application/ports/`. L'arborescence
interne reflète la nature du contrat, mais ne porte aucune règle
d'import :

- **`application/ports/repositories/`** — Protocols de persistance
  d'un agrégat (`PersonRepository`, `PublicationRepository`,
  `JournalRepository`, `StructureRepository`, `AuthorshipRepository`,
  `AddressRepository`, `PublisherRepository`, `PerimeterRepository`,
  `AuditRepository`). Signatures en termes métier (`find_by_doi`,
  `create`, `merge_into`), types `domain/` + primitives Python.
- **`application/ports/api/`** — query services lectures pour les
  routers (facets, listings, projections plates).
- **`application/ports/pipeline/`** — query services et opérations
  spécifiques à une phase pipeline. Signature typique : `Connection`
  SA en premier argument.
- **`application/ports/<nom>.py`** (racine) — autres ports
  applicatifs sans famille (ex. `config.py`).

**Exception assumée pour les repositories** :
- `address_repository` expose des méthodes de propagation
  cross-aggregate (ex. `refresh_publications_countries_for_addresses`)
  qui touchent `publications.countries`. Pattern accepté en DDD quand
  les agrégats sont étroitement liés et que la propagation fait
  partie de la cohérence métier.

### `application/` — services et orchestrateurs

Contenu :
- **Services métier** : `persons.py`, `publications.py`, `journals.py`,
  `authorships/core.py`, `authorships/assign_orphans.py`,
  `structures.py`, `addresses_countries.py`, `addresses_structures.py`,
  `audit.py`, `config.py`, `publishers.py`. Ces services reçoivent
  leurs dépendances par injection (kwarg `repo=`, `audit_repo=`,
  `queries=`).
- **Orchestrateurs pipeline** dans `application/pipeline/` :
  - `extract/` — tous les pilotes d'ingestion → staging :
    - `extract_<source>.py` — extraction de masse par source (HAL,
      OpenAlex, WoS, ScanR, theses.fr) ; pilote la pagination
    - `fetch_missing_doi.py` — fetch cross-source par DOI
    - `fetch_missing_hal_id.py` — fetch HAL par halId / NNT depuis
      les références d'autres sources
    - `refetch_truncated.py` — re-fetch OpenAlex des works tronqués
      à 100 auteurs

    Chaque pilote délègue HTTP + SQL à un adapter via un Port
    (`application/ports/pipeline/extract/<nom>.py`).
  - `normalize/` — staging → tables sources (un module par source)
  - `affiliations/` — propagation adresses ↔ structures vers
    `source_authorships.in_perimeter` et la table de jointure
    `source_authorship_structures`
  - `publications/` — création/merge publications canoniques
  - `persons/` — création personnes + formes de noms
  - `authorships/` — reconstruction de la table de vérité
  - `countries/` — recalcul pays publications
  - `subjects/` — ingestion sujets/mots-clés
  - `cooccurrences/` — recalcul co-occurrences sujets
  - `enrich/` — Unpaywall, APC
- **Ports** (`application/ports/*`) : interfaces Protocol pour les
  query services (adapters dans `infrastructure/queries/*`) et
  pour les repositories d'agrégats (`application/ports/repositories/*`,
  implémentés dans `infrastructure/repositories/*`).

Interdiction : **`application/` ne peut pas importer
`infrastructure/`**. Toute nouvelle dépendance doit passer par un
port. Vérifié par le contrat `layered` d'`import-linter`.

### `infrastructure/` — adapters sortants

Contenu :
- **`db/`** — bas niveau DB (engine, schéma, MetaData) :
  - `schema.sql` (snapshot descriptif, régénéré par
    `python -m infrastructure.db.dump_schema`), `seed.sql`
  - `tables.py` — MetaData SQLAlchemy explicite (source pour
    `alembic revision --autogenerate`). Les migrations vivent dans
    `alembic/versions/` à la racine, appliquées via
    `alembic upgrade head`.
  - `engine.py` — Engine SQLAlchemy synchrone (driver
    `postgresql+psycopg`). Source unique pour l'API FastAPI (via le
    threadpool Starlette) et le pipeline.
- **`queries/`** — query services SQL : projections plates pour
  lectures (listings, facets, détails, stats). Implémentent les ports
  `application/ports/api/*` et `application/ports/pipeline/*`. Un
  fichier par agrégat ou phase pipeline ; les modules volumineux sont
  éclatés en sous-dossier (`queries/persons/`, `queries/publications/`
  pour `list.py`, `facets.py`, `detail.py`, …).
- **`repositories/`** — adapters PostgreSQL implémentant les ports
  `application/ports/repositories/*` : `person_repository/`, `publication_repository.py`,
  `journal_repository.py`, `structure_repository.py`,
  `authorship_repository.py`, `address_repository.py`,
  `publisher_repository.py`, `perimeter_repository.py`,
  `audit_repository.py`. Factories exposées dans `__init__.py`
  (`person_repository(conn)`, `publication_repository(conn)`, …).
- **`jsonb_models/`** — modèles Pydantic des colonnes JSONB
  (`publications.external_ids`, `structures.api_ids`, …). Validation +
  normalisation à l'écriture, parsing typé à la lecture. Pas de
  dépendance SQLAlchemy : c'est de la modélisation de données, juste
  rangée côté infra parce que la forme est dictée par le schéma DB.
- **`sources/`** — adapters HTTP/SQL des sources externes (HAL, OpenAlex,
  WoS, ScanR, theses.fr, Crossref). Pour la phase extract, chaque source
  expose un `Pg<Source>ExtractAdapter` qui implémente le port
  `application.ports.pipeline.extract.<source>.<Source>ExtractAdapter` ;
  l'orchestrateur (qui hérite du `SourceExtractor` de
  `application/pipeline/extract/base.py`) vit côté application. Inclut
  aussi `zenodo/` (adapter HTTP de résolution concept DOI → version DOI,
  utilisé pendant la normalisation HAL et OpenAlex).
- **Divers** : `log.py` (JSON structuré), `settings.py`
  (pydantic-settings), `perimeter.py`, `addresses.py`,
  `api_retry.py`, `api_limits.py`, `pipeline_metrics.py`,
  `pipeline_status.py`, `app_config.py`, `db/dump_schema.py`.

**Pourquoi `queries/` ET `repositories/` au lieu d'une seule
abstraction SQL ?** C'est un compromis CQRS-light :
- `repositories/` est orienté **écriture + invariants** : hydrate des
  agrégats riches (`Publication`, `Person`, …) avec leurs VOs et
  règles métier, garantit la cohérence à l'écriture. Signatures en
  termes métier (`find_by_doi`, `merge_into`, `save`).
- `queries/` est orienté **lecture pour l'UI** : projections plates,
  jointures, agrégations, filtres dynamiques (facets). Retourne des
  records (`dict[str, object]` ou `Row[Any]`) directement
  consommables par les routers et leur Pydantic ; pas d'hydratation
  d'agrégat.

Hydrater une `Publication` complète pour afficher une ligne dans une
liste de 50 publis serait du gaspillage. Inversement, faire passer une
écriture d'agrégat par une projection SQL ad-hoc fragiliserait les
invariants. Les deux abstractions cohabitent donc volontairement.

`infrastructure/` n'importe que les ports (`application/ports/*`)
et le domaine — jamais les use-cases applicatifs (`application/*.py`
hors `ports/`).

### `interfaces/` — adapters entrants

Contenu :
- **`api/`** — FastAPI :
  - `app.py` — entry point (routers, middlewares, gestion d'erreurs)
  - `routers/` — un module par agrégat (publications, persons,
    laboratories, addresses, …)
  - `models.py` — Pydantic pour les bodies POST/PUT/PATCH
  - `deps.py` — dépendances (Engine SA sync, factories de query
    services et de repositories, auth)
  - middlewares inline dans `app.py` (auth, strip-prefix, timing)
- **`frontend/`** — SvelteKit (Svelte 5)
- **`cli/`** — scripts one-shot (imports manuels, debug, corrections
  ponctuelles). Exclus de la couverture pytest
  (`[tool.coverage.run]` omit).

## Patterns d'injection

### Sync partout (FastAPI + threadpool)

Toutes les routes API sont déclarées `def` (pas `async def`). FastAPI
les exécute dans le threadpool Starlette (~40 workers par défaut), ce
qui permet de partager **les mêmes** repositories et query services
entre l'API et le pipeline. Une seule famille de code, un seul style
de connexion (`Connection` SQLAlchemy).

L'unique exception : `feedback_rerun` dans `admin_feedback.py` reste
`async def` parce qu'il streame du SSE depuis un subprocess
(`asyncio.create_subprocess_exec` + `StreamingResponse`). Aucune
connexion DB en jeu, cohabitation supportée par FastAPI.

Dimensionnement du pool DB : `db_pool_max = 30` (dans
`infrastructure/settings.py`), pour absorber confortablement la
concurrence threadpool × marge sur un usage admin
(quelques utilisateurs concurrents max). Bumper si on observe des
`TimeoutError` côté pool sous charge anormale (cf. `.env.example`).

### Services applicatifs ↔ repositories

Les services acceptent leur repo (et autres dépendances : audit_repo,
queries, …) en kwarg keyword-only :

```python
def set_rejected(
    person_id: int,
    rejected: bool,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    repo.set_rejected(person_id, rejected)
    emit_event(audit_repo, "person.rejected", ...)
```

Les callers directs (routers, tests, scripts CLI) créent l'instance
via la factory :

```python
from infrastructure.repositories import person_repository
set_rejected(person_id, True, repo=person_repository(conn))
```

### Orchestrateurs pipeline ↔ query services + repositories

Les orchestrateurs dans `application/pipeline/*` ne peuvent pas
importer `infrastructure.*` directement. Deux mécanismes :

1. **Query services** (SQL de la phase) : passés en paramètre
   typés par un port `application/ports/*`. L'entry point
   (`run_pipeline.py` ou `interfaces/cli/pipeline/*`) instancie les
   adapters `Pg*Queries` concrets.

2. **Repositories** (ex. `PublicationRepository`) : quand un
   orchestrateur a besoin d'un repo, on passe un **factory callable**
   `repo_factory: Callable[[Connection], XRepository]` au constructeur.
   L'orchestrateur appelle `self._repo = self._repo_factory(conn)` dans
   `preload_caches()` ou au début de `run()`.

Exemple depuis `run_pipeline.py` :

```python
from infrastructure.queries.persons_create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository

PgPersonsCreateQueries()        # adapter query service
person_repository(conn)         # factory repository
```

## Pipeline

L'orchestrateur `run_pipeline.py` à la racine enchaîne les phases du
pipeline de peuplement. Chaque phase est idempotente (relançable sans
risque) ; reprise depuis une phase donnée :
`python run_pipeline.py --from <phase>`.

Voir [pipeline](pipeline) pour la liste des phases et le détail de
chacune.

## Tests

- **Unit** (`tests/unit/`) — pas de DB. Couvre `domain/`,
  `application/` (services avec mocks), parsing des normalizers et
  des adapters sources (`infrastructure/sources/<source>/parsing.py`),
  infrastructure pure (log, pipeline_metrics).
- **Intégration** (`tests/integration/`) — base `bibliometrie_test`
  créée à la volée (`alembic upgrade head` sur DB vierge), fixtures
  `db` (curseur psycopg avec rollback) et `sa_sync_conn` (Connection
  SA avec rollback). Couvre les routers, les orchestrateurs pipeline,
  et les adapters repositories.

Conftest splitté :
- `tests/conftest.py` — cross-cutting (mock `setup_logger` pour
  éviter la pollution disque, caches)
- `tests/integration/conftest.py` — setup BDD via Alembic, fixtures
  `db` / `sa_sync_conn`

Seuil de couverture `fail_under = 85` (`[tool.coverage.report]` dans
`pyproject.toml`). Mesure courante : 86 %.
Les modules de wiring HTTP des adapters sources sont exclus du calcul ;
leur logique pure vit dans `<source>/parsing.py` et est couverte par
tests unitaires.

## Composition roots

Le composition root est l'endroit où les adapters concrets sont
**instanciés** et **câblés** aux use-cases. Il a, par nature, le
droit d'importer `infrastructure.*` directement — c'est son rôle.
Partout ailleurs, on reçoit un port en paramètre.

Les fichiers qui jouent ce rôle :

- `interfaces/api/app.py` — entry point FastAPI (startup, lifespan,
  middlewares, montage des routers)
- `interfaces/api/deps.py` — factories partagées par les routers :
  `db_conn_sync` (Connection SA), query services et repositories
  câblés sur cette Connection
- `run_pipeline.py` — orchestrateur pipeline complet
- `interfaces/cli/pipeline/*` — entry points CLI pour chaque phase
- `interfaces/cli/*` — scripts one-shot

**Seuls** ces fichiers importent `infrastructure.repositories`,
`infrastructure.queries.*` ou toute classe `Pg*` concrète.

- **Côté API** : `app.py` / `deps.py` sont les composition roots ;
  les routers individuels (`interfaces/api/routers/*`) reçoivent
  leurs dépendances via `Depends(...)` et **n'importent pas**
  `infrastructure.*` directement. Verrouillé par le contrat
  `import-linter` "Routers : pas d'import direct de infrastructure".
- **Côté CLI** : chaque script (`interfaces/cli/*`, y compris
  `interfaces/cli/pipeline/*`) **est** son propre composition root.
  Il importe les adapters concrets, instancie les factories, et
  appelle un use case applicatif en lui passant tout en kwargs.
  Pas de séparation construct/appel comme côté API ; cohérent avec
  la nature one-shot des scripts. Pas de contrat `import-linter`
  côté CLI, la discipline reste manuelle : `application/` et
  `domain/` ne doivent jamais importer `infrastructure/`, et le
  script CLI doit rester un thin wrapper (imports + instanciations
  + appel d'un use case ; pas de logique métier dans le script).

## Pour aller plus loin

- [donnees](donnees) — modèle de données
- [pipeline](pipeline) — détail des phases
- [sources](sources) — API et imports par source
