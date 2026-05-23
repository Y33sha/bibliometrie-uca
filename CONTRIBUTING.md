# Contribuer au projet

*Document à jour au 2026-05-16.*

Guide opérationnel pour étendre bibliometrie-uca. Trois axes :

1. [Ajouter une nouvelle source de données](#ajouter-une-nouvelle-source-de-donnees)
2. [Ajouter une phase au pipeline](#ajouter-une-phase-au-pipeline)
3. [Ajouter un endpoint API](#ajouter-un-endpoint-api)

Prérequis : comprendre l'architecture DDD en 4 couches — voir [`docs/architecture/`](docs/architecture/). Le modèle de données est documenté dans [`docs/donnees/`](docs/donnees/) ; le pipeline complet dans [`docs/pipeline/`](docs/pipeline/).

## Conventions transverses

- **SQL** : toujours des requêtes paramétrées. Le code applicatif passe par SQLAlchemy Core (`text(...).bindparams(...)`, `select(...).where(...)`, `update(...).values(...)`) avec des paramètres nommés `:name`. Le shim psycopg direct (`cur.execute(...)`, encore utilisé dans quelques tests d'intégration et helpers low-level) reste en `%s`. Aucune interpolation f-string pour des valeurs. Le seul cas de f-string toléré est la construction dynamique d'un `WHERE` ou d'un `ORDER BY` à partir de fragments **figés** (cf. `infrastructure/queries/persons/`).
- **Logging** : `setup_logger` de `infrastructure/log.py` pour les scripts CLI (`interfaces/cli/`) et les extracteurs ; `logging.getLogger(__name__)` dans le code applicatif (routers, services, queries) — le root logger est configuré au démarrage de l'app.
- **Noms de personnes / DOI** : `names_compatible`, `parse_raw_author_name` de `domain/names.py` ; `DOI`, `DOI.try_parse` de `domain/publication.py`.
- **Couches DDD** : le contrat `import-linter` interdit certaines directions d'import (`domain/` ne peut rien importer, `application/` ne peut pas importer `infrastructure/`, etc.). Un import interdit fera échouer le pre-commit et la CI.
- **Tests** : `python -m pytest tests/ -v` (la base `DB_PASSWORD` doit être exportée). Les tests unitaires (`tests/unit/`) tournent aussi au pre-commit. Seuil de couverture global : `fail_under = 85` dans `pyproject.toml`, à faire monter progressivement (cf. `docs/chantiers/CODE_couverture-tests.md`).
- **Pre-commit** : lance ruff + ruff format + mypy + lint-imports + pytest-unit + uv-lock. Lancer `ruff format .` avant `git commit` évite le double-commit quand le hook reformate.

---

## Ajouter une nouvelle source de données

Exemple : intégrer une nouvelle base bibliographique (ArXiv, PubMed, DataCite). Le projet a déjà six sources intégrées : HAL, OpenAlex, WoS, Scanr, theses.fr, CrossRef.

Une source couvre 3 étapes du pipeline : **extract** (API → staging), **fetch_missing_doi** ou autre rattrapage cross-source (hydrate dans une source les DOIs détectés ailleurs), **normalize** (staging → tables structurées `source_*`).

### 1. Enregistrer la source

Dans [`domain/sources/__init__.py`](domain/sources/__init__.py), ajouter l'identifiant à `ALL_SOURCES` et, si pertinent, à `BIBLIO_SOURCES` (sources bibliographiques au sens strict, qui excluent theses.fr).

```python
ALL_SOURCES = ("hal", "openalex", "wos", "scanr", "theses", "crossref", "ma_source")
BIBLIO_SOURCES = ("hal", "openalex", "wos", "scanr", "crossref", "ma_source")
```

Côté base, ajouter la valeur à l'enum Postgres `source_type` via une migration Alembic (cf. [`alembic/versions/2026_05_16_1015-0013_source_text_to_enum.py`](alembic/versions/2026_05_16_1015-0013_source_text_to_enum.py) pour la doctrine).

### 2. Extractor : API → `staging`

L'extraction suit le pattern hexagonal en 5 morceaux :

- `domain/sources/<source>_extract.py` — constantes + helpers purs (parsing, requête, rate-limit)
- `application/ports/pipeline/extract/<source>.py` — `Protocol` `<Source>ExtractAdapter` + dataclass `<Source>ExtractConfig`
- `application/pipeline/extract/extract_<source>.py` — orchestrateur (`<Source>Extractor` héritant de `SourceExtractor` de [`application/pipeline/extract/base.py`](application/pipeline/extract/base.py))
- `infrastructure/sources/<source>/extract_<source>.py` — adapter Postgres (`Pg<Source>ExtractAdapter`) qui implémente le port (HTTP + SQL)
- `interfaces/cli/pipeline/extract_<source>.py` — entry point CLI (thin wrapper)

```python
# application/pipeline/extract/extract_ma_source.py
from application.pipeline.extract.base import SourceExtractor
from application.ports.pipeline.extract.ma_source import MaSourceExtractAdapter, MaSourceExtractConfig

class MaSourceExtractor(SourceExtractor[MaSourceExtractConfig]):
    SOURCE = "ma_source"
    DESCRIPTION = "Extraction MaSource → staging"

    def __init__(self, conn, logger, staging, adapter):
        super().__init__(conn, logger, staging)
        self._adapter = adapter

    def load_config(self, conn):
        return self._adapter.load_config(conn)

    def extract_all(self, args, config, existing_ids) -> PhaseMetrics:
        # Boucle d'itération spécifique ; appelle `adapter.fetch_page`,
        # `adapter.insert_batch` / `adapter.upsert_*`.
        ...
```

Modèles à copier : [`application/pipeline/extract/extract_theses.py`](application/pipeline/extract/extract_theses.py) (structure simple, pas de spécificité HAL) avec [`application/ports/pipeline/extract/theses.py`](application/ports/pipeline/extract/theses.py) et [`infrastructure/sources/theses/extract_theses.py`](infrastructure/sources/theses/extract_theses.py).

### 3. Fetch missing DOI : hydratation cross-source

Adapter `infrastructure/sources/<source>/fetch_missing_doi.py` qui, pour chaque DOI présent dans d'autres sources mais absent de la nôtre, va chercher les métadonnées et les ajoute en staging. Le dispatcher CLI unique [`interfaces/cli/pipeline/fetch_missing_doi.py`](interfaces/cli/pipeline/fetch_missing_doi.py) appelle l'adapter de la source demandée.

S'inspirer de [`infrastructure/sources/openalex/fetch_missing_doi.py`](infrastructure/sources/openalex/fetch_missing_doi.py).

### 4. Normalizer : staging → tables structurées

Créer `application/pipeline/normalize/normalize_<source>.py` héritant de `SourceNormalizer` (cf. [`application/pipeline/normalize/base.py`](application/pipeline/normalize/base.py)). Override de `process_work(cur, row)` qui insère dans `source_publications` et `source_authorships`.

Point d'entrée CLI dans `interfaces/cli/pipeline/normalize_<source>.py` : charge la connexion, injecte `StagingQueries` (port défini dans [`application/ports/pipeline/staging.py`](application/ports/pipeline/staging.py)), instancie le normalizer.

Modèle : [`interfaces/cli/pipeline/normalize_theses.py`](interfaces/cli/pipeline/normalize_theses.py).

### 5. Brancher dans le pipeline

Dans [`run_pipeline.py`](run_pipeline.py), ajouter les appels dans `phase_extract()`, `phase_cross_imports()` (cross-import via DOI ou HAL-ID), et `phase_normalize()`. Pas de nouvelle entrée dans `PHASES` — une source s'intègre aux phases existantes, ce n'est **pas** une phase.

### 6. Migration SQL éventuelle

Si la source ajoute des colonnes (`source_publications.nouveau_champ`), mettre à jour la MetaData dans [`infrastructure/db/tables.py`](infrastructure/db/tables.py), générer la migration Alembic via `alembic revision --autogenerate -m "<description>"`, relire le fichier produit dans [`alembic/versions/`](alembic/versions/) et appliquer via `alembic upgrade head`.

---

## Ajouter une phase au pipeline

Les phases existantes sont déclarées dans [`run_pipeline.py`](run_pipeline.py) à la variable `PHASES` (liste ordonnée de `(nom, fonction)`). L'ordre courant : `extract → cross_imports → normalize → affiliations → publications → persons → authorships → countries → subjects → enrich`. Chaque phase reçoit `**kw` (mode, sources, year) et orchestre des sous-étapes.

### 1. Écrire la logique métier

Une phase simple = une fonction dans `application/pipeline/<catégorie>/<script>.py` avec la signature `run(conn, queries, logger, *, repo=..., audit_repo=None)` où `conn` est une `sqlalchemy.Connection` sync, `queries` est un port d'accès en lecture (`application/ports/...`), et les `repo` sont les ports d'écriture injectés par le composition root.

Si la phase touche plusieurs entités et mérite un sous-package, la découper comme `application/pipeline/publications/`, `persons/`, etc.

### 2. Port + adapter SQL

Si la phase fait du SQL non trivial :

- Protocol `application/ports/pipeline/<phase>.py` (ou `application/ports/api/<phase>_queries.py` côté lecture) définissant l'interface.
- Adapter `infrastructure/queries/<phase>.py` qui l'implémente.
- Le port est injecté par le composition root (le CLI one-shot, l'orchestrateur `run_pipeline.py`, ou les dépendances FastAPI), jamais instancié dans la couche application.

### 3. Entry-point CLI

`interfaces/cli/pipeline/<nouvelle_phase>.py` : ouvre une `Connection` SA via `get_sync_engine().connect()` (ou `.begin()` si la phase doit committer en bloc), instancie l'adapter SQL, appelle la fonction `run(...)`, commit, close.

Utile pour rejouer la phase à la main sans relancer tout le pipeline.

### 4. Brancher dans `run_pipeline.py`

```python
def phase_<name>(**kw: Any) -> Any:
    log.info("▶ phase <name>")
    t0 = time.time()
    # Appels aux helpers _run_*() ou run_python(<script CLI>)
    log.info("✓ <name> terminée en %.1fs", time.time() - t0)

PHASES = [
    ...,
    ("<name>", phase_<name>),
]
```

Respecter l'ordre : une phase dépend en général des sorties de la précédente (ex. `persons` a besoin que `affiliations` soit terminée).

### 5. Documenter

Ajouter une entrée dans [`docs/pipeline.md`](docs/pipeline.md) qui décrit : ce que la phase fait, ses prérequis, ses sorties, les idempotences à préserver.

---

## Ajouter un endpoint API

Architecture DDD-lite : le router délègue à un service d'`application/`, qui délègue à un repository (`application/ports/repositories/`) ou à un query adapter (`application/ports/api/`) d'`infrastructure/`. L'app est **sync** (Starlette threadpool sous le capot) : pas de `async def` dans les routers et les services.

### 1. Modèle Pydantic (obligatoire pour POST/PUT/PATCH)

Les modèles sont splittés par router dans le package [`interfaces/api/models/`](interfaces/api/models/) (un fichier par domaine + `_common.py` pour les types partagés). Créer ou compléter le fichier `interfaces/api/models/<domaine>.py` puis exporter dans `interfaces/api/models/__init__.py`. **Jamais `body: dict`** : c'est un casseur de contrat OpenAPI → TypeScript.

```python
# interfaces/api/models/foos.py
from pydantic import BaseModel

class FooCreate(BaseModel):
    name: str
    active: bool = True

class FooOut(BaseModel):
    id: int
    name: str
    active: bool
```

### 2. Service métier (`application/`)

Dans `application/<domaine>.py`, ajouter la fonction métier. Elle reçoit ses ports en kwargs explicites et lève des exceptions `domain.errors` sans connaître HTTP :

```python
from domain.errors import NotFoundError, ValidationError, ConflictError
from application.ports.repositories.foo_repository import FooRepository

def create_foo(*, name: str, active: bool, repo: FooRepository) -> dict:
    if not name.strip():
        raise ValidationError("Le nom est requis")
    if repo.exists_by_name(name):
        raise ConflictError(f"Un foo '{name}' existe déjà")
    return repo.create(name=name, active=active)
```

Les `@app.exception_handler` d'[`interfaces/api/app.py`](interfaces/api/app.py) mappent ces exceptions → codes HTTP (404, 400, 409, 401). **Ne pas lever `HTTPException` dans un service** : c'est une fuite HTTP dans la couche application.

### 3. Dépendances FastAPI

Dans [`interfaces/api/deps.py`](interfaces/api/deps.py), ajouter (s'il n'existe pas déjà) un provider sync qui dérive de `db_conn_sync` :

```python
def foo_repo_sync(conn: Connection = Depends(db_conn_sync)) -> FooRepository:
    return foo_repository(conn)

def foo_queries_sync(conn: Connection = Depends(db_conn_sync)) -> FooQueries:
    return PgFooQueries(conn)
```

`db_conn_sync` ouvre `engine.begin()` : commit auto en sortie sans exception, rollback sinon. Toutes les dépendances dérivées partagent la même connexion → même transaction.

### 4. Router

Créer ou éditer `interfaces/api/routers/<domaine>.py` :

```python
from fastapi import APIRouter, Depends, HTTPException
from application.foos import create_foo as _create_foo
from application.ports.repositories.foo_repository import FooRepository
from interfaces.api.deps import foo_repo_sync
from interfaces.api.models import FooCreate, FooOut

router = APIRouter()

@router.post("/api/foos", response_model=FooOut)
def create_foo(
    body: FooCreate,
    repo: FooRepository = Depends(foo_repo_sync),
) -> FooOut:
    """Crée un foo. Renvoie 409 si un foo du même nom existe déjà."""
    row = _create_foo(name=body.name, active=body.active, repo=repo)
    return FooOut(**row)
```

Le **docstring** de l'endpoint est repris dans l'OpenAPI (`description`) — écrire une phrase utile, pas un placeholder. `response_model` est obligatoire pour que le type soit généré côté TypeScript.

### 5. Enregistrer le router

Dans [`interfaces/api/app.py`](interfaces/api/app.py), ajouter l'import dans le bloc `from interfaces.api.routers import (...)` puis `app.include_router(foos.router)` dans le bloc d'inclusion.

### 6. Tests

Ajouter un test dans `tests/integration/interfaces/test_<domaine>_api.py`. Pattern de référence : [`tests/integration/interfaces/test_publishers_api.py`](tests/integration/interfaces/test_publishers_api.py) (structure compacte) ou [`test_persons_api.py`](tests/integration/interfaces/test_persons_api.py) (endpoints nombreux, helpers de seed).

Points à ne pas oublier :

- **Admin guard** : les endpoints POST/PUT/PATCH/DELETE sont protégés par le middleware `auth_middleware` global ([`interfaces/api/app.py`](interfaces/api/app.py)). Tester le 401 avec `client` (non authentifié) et le happy path avec `auth_client`.
- **Fixture cleanup** : si les mutations committent dans la base, ajouter une fixture module-scope `autouse` qui `TRUNCATE` les tables impactées après la suite, pour ne pas polluer les tests pipeline / audit qui tournent après.

### 7. Régénérer les types TypeScript

```bash
cd interfaces/frontend
npm run types:gen
```

Le script dump l'OpenAPI offline ([`interfaces/cli/dev/dump_openapi.py`](interfaces/cli/dev/dump_openapi.py)), le convertit en TypeScript via `openapi-typescript` et écrit dans `src/lib/api/schema.ts` (source de vérité côté front). Committer `schema.ts` dans le même PR.

---

## Workflow de contribution

1. Créer une branche `feature/<nom>` depuis `master`.
2. Coder, tester (`pytest tests/ -v`, `npm run check` côté frontend si front touché).
3. `ruff format .` avant de committer (évite le double-commit du pre-commit hook).
4. Commits atomiques, messages en français, référence à la fiche chantier concernée dans [`docs/chantiers/`](docs/chantiers/) quand applicable.
5. Merge en `--no-ff` pour garder la trace du chantier.
