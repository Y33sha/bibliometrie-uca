# Contribuer au projet

Guide opérationnel pour étendre la bibliométrie UCA. Trois axes :

1. [Ajouter une nouvelle source de données](#ajouter-une-nouvelle-source-de-donnees)
2. [Ajouter une phase au pipeline](#ajouter-une-phase-au-pipeline)
3. [Ajouter un endpoint API](#ajouter-un-endpoint-api)

Prérequis : comprendre l'architecture DDD en 4 couches — voir
[`docs/architecture.md`](docs/architecture.md). Le modèle de données
est documenté dans [`docs/donnees.md`](docs/donnees.md) ; le pipeline
complet dans [`docs/pipeline.md`](docs/pipeline.md).

## Conventions transverses

- **SQL** : toujours des requêtes paramétrées (`%s`), jamais
  d'interpolation f-string pour les valeurs. Le seul cas de f-string
  toléré est la construction dynamique d'un `WHERE` ou d'un
  `ORDER BY` à partir de fragments figés (cf. `queries/persons/`).
- **Logging** : `setup_logger` de `infrastructure/log.py` pour les
  scripts CLI ; `logging.getLogger(__name__)` dans le code applicatif
  (routers, services) — le root logger est configuré au démarrage de
  l'app.
- **Noms de personnes / DOI** : `names_compatible`,
  `parse_raw_author_name` de `domain/names.py` ; `DOI`, `DOI.try_parse`
  de `domain/publication.py`.
- **Couches DDD** : le contrat `import-linter` interdit certaines
  directions d'import (`domain/` ne peut rien importer,
  `application/` ne peut pas importer `infrastructure/`, etc.). Un
  import interdit fera échouer le pre-commit et la CI.
- **Tests** : `python -m pytest tests/ -v` (la base `DB_PASSWORD`
  doit être exportée). Les tests unitaires (`tests/unit/`) tournent
  aussi au pre-commit. Seuil de couverture global : `fail_under = 62`
  dans `pyproject.toml`, à faire monter progressivement.
- **Pre-commit** : lance ruff + ruff format + mypy + lint-imports +
  pytest-unit + uv-lock. Lancer `ruff format .` avant `git commit`
  évite le double-commit quand le hook reformate.

---

## Ajouter une nouvelle source de données

Exemple : intégrer CrossRef, ArXiv, PubMed, DataCite.

Une source couvre 3 étapes du pipeline : **extract** (API → staging),
**cross_imports** (hydrate les DOIs manquants détectés par d'autres
sources), **normalize** (staging → tables structurées `source_*`).

### 1. Enregistrer la source

Dans [`domain/sources.py`](domain/sources.py), ajouter l'identifiant :

```python
ALL_SOURCES = ("hal", "openalex", "wos", "scanr", "theses", "crossref")
BIBLIO_SOURCES = ("hal", "openalex", "wos", "scanr", "crossref")
```

`BIBLIO_SOURCES` exclut les sources qui ne sont pas bibliographiques
au sens strict (comme `theses` qui a un traitement spécifique).

### 2. Extractor : API → `staging`

Créer [`infrastructure/sources/<source>/extract_<source>.py`] héritant
de `SourceExtractor` (voir
[`infrastructure/sources/base.py`](infrastructure/sources/base.py#L52)).
Le template gère parsing CLI, cycle connexion, chargement
`existing_ids`, gestion des erreurs HTTP/interruption, logs.

```python
from infrastructure.log import setup_logger
from infrastructure.sources.base import SourceExtractor, ExtractionStats, run_extractor

class CrossRefExtractor(SourceExtractor):
    SOURCE = "crossref"
    DESCRIPTION = "Extraction CrossRef → staging"

    def load_config(self, cur):
        # Lire URL/API key depuis la table `config` (DOIs, mailto, …).
        ...

    def extract_all(self, args, config, existing_ids) -> ExtractionStats:
        stats = ExtractionStats()
        # Itération spécifique (cursor CrossRef, pagination, …).
        # Insérer en staging(source, source_id, raw_data).
        return stats

if __name__ == "__main__":
    logger = setup_logger("extract_crossref", "infrastructure/sources/crossref/logs")
    run_extractor(CrossRefExtractor, logger)
```

Modèle à copier : [`infrastructure/sources/theses/extract_theses.py`](infrastructure/sources/theses/extract_theses.py)
(structure simple, pas de spécificité HAL).

### 3. Cross-import : hydratation des DOIs

Script autonome `infrastructure/sources/<source>/cross_import_<source>.py`
qui, pour chaque DOI présent dans d'autres sources mais absent de la
nôtre, va chercher les métadonnées et les ajoute en staging.

Pas de base class ici — s'inspirer de
[`infrastructure/sources/openalex/cross_import_openalex.py`](infrastructure/sources/openalex/cross_import_openalex.py).

### 4. Normalizer : staging → tables structurées

Créer [`application/pipeline/normalize/normalize_<source>.py`] héritant
de `SourceNormalizer` (voir
[`application/pipeline/normalize/base.py`](application/pipeline/normalize/base.py#L27)).
Override de `process_work(cur, row)` qui insère dans `source_publications`,
`source_authorships`, `source_persons`.

Point d'entrée CLI dans [`interfaces/cli/pipeline/normalize_<source>.py`] :
charge la connexion, injecte `StagingQueries` (port défini dans
`application/ports/staging.py`), instancie le normalizer.

Modèle : [`interfaces/cli/pipeline/normalize_theses.py`](interfaces/cli/pipeline/normalize_theses.py).

### 5. Brancher dans le pipeline

Dans [`run_pipeline.py`](run_pipeline.py), ajouter les appels dans
`phase_extract()`, `phase_cross_imports()`, et
`_run_normalize_<source>()`. Pas de nouvelle entrée dans `PHASES` —
une source s'intègre aux phases existantes, ce n'est **pas** une phase.

### 6. Migration SQL éventuelle

Si la source ajoute des colonnes (`source_publications.nouveau_champ`),
écrire la migration dans [`infrastructure/db/migrations/NNN_<nom>.sql`]
(numérotation séquentielle à 3 chiffres) et appliquer via
`python -m infrastructure.db.migrate`.

---

## Ajouter une phase au pipeline

Les phases existantes sont déclarées dans
[`run_pipeline.py`](run_pipeline.py) à la variable `PHASES` (liste
ordonnée de `(nom, fonction)`). Chaque phase reçoit `**kw` (mode,
sources, year) et orchestre des sous-étapes.

### 1. Écrire la logique métier

Une phase simple = une fonction dans
[`application/pipeline/<catégorie>/<script>.py`] avec la signature
`run(cur, conn, queries, log, **kwargs)` où `queries` est un port
injecté.

Si la phase touche plusieurs entités et mérite un sous-package, la
découper comme `application/pipeline/publications/`, `persons/`, etc.

### 2. Port + adapter SQL

Si la phase fait du SQL non trivial :

- Protocol `application/ports/<phase>.py` définissant l'interface.
- Adapter `infrastructure/db/queries/<phase>.py` qui l'implémente.
- Le port est injecté par le composition root (le CLI one-shot ou
  `run_pipeline.py`), jamais instancié dans la couche application.

### 3. Entry-point CLI

`interfaces/cli/pipeline/<nouvelle_phase>.py` : charge la connexion via
`get_connection()`, instancie l'adapter SQL, appelle la fonction
d'orchestration, commit, close.

Utile pour rejouer la phase à la main sans relancer tout le pipeline.

### 4. Brancher dans `run_pipeline.py`

```python
def phase_<name>(**kw):
    log.info("▶ phase <name>")
    t0 = time.time()
    # Appels aux helpers _run_*()
    log.info("✓ <name> terminée en %.1fs", time.time() - t0)

PHASES = [
    ...,
    ("<name>", phase_<name>),
]
```

Respecter l'ordre : une phase dépend en général des sorties de la
précédente (ex. `persons` a besoin que `affiliations` soit terminée).

### 5. Documenter

Ajouter une entrée dans [`docs/pipeline.md`](docs/pipeline.md) qui
décrit : ce que la phase fait, ses prérequis, ses sorties, les
idempotences à préserver.

---

## Ajouter un endpoint API

Architecture DDD-lite : le router délègue à un service
d'`application/`, qui délègue à un repository d'`infrastructure/`.

### 1. Modèle Pydantic (obligatoire pour POST/PUT/PATCH)

Dans [`interfaces/api/models.py`](interfaces/api/models.py), ajouter
les `BaseModel` d'entrée et de sortie. **Jamais `body: dict`** : c'est
un casseur de contrat OpenAPI → TypeScript.

```python
class FooCreate(BaseModel):
    name: str
    active: bool = True

class FooOut(BaseModel):
    id: int
    name: str
    active: bool
```

### 2. Service métier (`application/`)

Dans [`application/<domaine>.py`](application/), ajouter la fonction
métier. Elle reçoit le curseur + un repository injecté, et lève des
exceptions `domain.errors` sans connaître HTTP :

```python
from domain.errors import NotFoundError, ValidationError, ConflictError

def create_foo(cur, *, name: str, active: bool, repo: FooRepository) -> dict:
    if not name.strip():
        raise ValidationError("Le nom est requis")
    if repo.exists_by_name(name):
        raise ConflictError(f"Un foo '{name}' existe déjà")
    return repo.create(name=name, active=active)
```

Les handlers d'`interfaces/api/app.py` (lignes 70-94) mappent ces
exceptions → codes HTTP (404, 400, 409, 401). **Ne pas lever
`HTTPException` dans un service** : c'est une fuite HTTP dans la
couche application.

### 3. Router

Créer ou éditer `interfaces/api/routers/<domaine>.py` :

```python
from fastapi import APIRouter
from application import foos as foos_service
from infrastructure.repositories import async_foo_repository
from interfaces.api.async_deps import get_async_cursor
from interfaces.api.models import FooCreate, FooOut

router = APIRouter()

@router.post("/api/foos", response_model=FooOut)
async def create_foo(data: FooCreate):
    """Crée un foo. Renvoie 409 si un foo du même nom existe déjà."""
    async with get_async_cursor() as (cur, _conn):
        return await foos_service.create_foo(
            cur, name=data.name, active=data.active, repo=async_foo_repository(cur)
        )
```

Le **docstring** de l'endpoint est repris dans l'OpenAPI
(`description`) — écrire une phrase utile, pas un placeholder.
`response_model` est obligatoire pour que le type soit généré côté
TypeScript.

### 4. Enregistrer le router

Dans [`interfaces/api/app.py`](interfaces/api/app.py) (fin du fichier
section `Include routers`) :

```python
from interfaces.api.routers import foos
app.include_router(foos.router)
```

### 5. Tests

Ajouter un test dans
[`tests/integration/interfaces/test_<domaine>_api.py`]. Pattern de
référence :
[`tests/integration/interfaces/test_publishers_api.py`](tests/integration/interfaces/test_publishers_api.py)
(structure compacte) ou
[`test_persons_api.py`](tests/integration/interfaces/test_persons_api.py)
(endpoints nombreux, helpers de seed).

Points à ne pas oublier :

- **Admin guard** : les endpoints POST/PUT/PATCH/DELETE sont protégés
  par un middleware global (`interfaces/api/app.py:121`). Tester le
  401 avec `client` (non authentifié) et le happy path avec
  `auth_client`.
- **Fixture cleanup** : si les mutations committent dans la base
  (via le pool partagé), ajouter une fixture module-scope `autouse`
  qui `TRUNCATE` les tables impactées après la suite, pour ne pas
  polluer les tests pipeline / audit qui tournent après.

### 6. Régénérer les types TypeScript

```bash
cd interfaces/frontend
npm run types:gen
```

Le script dump l'OpenAPI offline
([`interfaces/cli/dev/dump_openapi.py`](interfaces/cli/dev/dump_openapi.py)),
le convertit en TypeScript via `openapi-typescript` et écrit dans
`src/lib/api/schema.ts` (source de vérité côté front). Committer
`schema.ts` dans le même PR.

---

## Workflow de contribution

1. Créer une branche `feature/<nom>` depuis `master`.
2. Coder, tester (`pytest tests/ -v`, `svelte-check` si front touché).
3. `ruff format .` avant de committer (évite le double-commit du
   pre-commit hook).
4. Commits atomiques, messages en français, référence au `§X.Y`
   de [`ROADMAP.md`](ROADMAP.md) quand applicable.
5. Merge en `--no-ff` pour garder la trace du chantier.
