# Chantier — Inversion de dépendance dans les routers

Commencé et terminé le 2026-05-06.

## Contexte

`docs/architecture.md` règle 4 dit :

> Les routers FastAPI et scripts CLI [...] **ne doivent pas** importer `infrastructure/` directement. Ils pilotent des use-cases applicatifs et reçoivent leurs dépendances ; ils ne les construisent pas.

État actuel : 18 routers sur 20 importent `infrastructure/`
directement (33 imports au total). La règle est documentée mais non
appliquée et `import-linter` ne la verrouille pas (couvre uniquement
les règles 1-3).

ROADMAP §1.6 trace le chemin : factories FastAPI `Depends(...)` pour
injecter les query services / repos dans les routers, équivalent
unit-of-work. Fait à moitié : pipeline OK, API à faire.

## Décision retenue

**Appliquer la règle.** La cohabitation avec SQLAlchemy Core
(chantier en cours) rend le surcoût faible : les ports d'agrégat
existent déjà, FastAPI a un système `Depends` natif, et le bénéfice
test (overrides via `app.dependency_overrides`) est concret même si
on reste majoritairement en intégration end-to-end.

## Pattern cible

Précédent : `PgAsyncPerimeterQueries` (`infrastructure/db/queries/perimeter.py`) implémente le port `AsyncPerimeterQueries`
(`application/ports/perimeter.py`) ; la factory `get_perimeter_queries`
vit dans `async_deps.py` (composition root légitime).

Pour les routers :

```python
# interfaces/api/async_deps.py (composition root, autorisé à importer infra)
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncConnection
from fastapi import Depends

from domain.ports.person_repository import AsyncPersonRepository
from infrastructure.repositories import async_person_repository

@asynccontextmanager
async def get_db_conn() -> AsyncIterator[AsyncConnection]:
    engine = get_async_engine()
    async with engine.begin() as conn:
        yield conn

async def get_person_repo(
    conn: AsyncConnection = Depends(get_db_conn)
) -> AsyncPersonRepository:
    return async_person_repository(conn)

# interfaces/api/routers/persons.py (interdit d'importer infra)
from domain.ports.person_repository import AsyncPersonRepository
from interfaces.api.async_deps import get_person_repo

@router.get(...)
async def my_endpoint(
    repo: AsyncPersonRepository = Depends(get_person_repo)
):
    ...
```

**Propriété clé** : FastAPI cache les `Depends` par requête, donc deux
endpoint deps qui dépendent toutes deux de `get_db_conn` partagent la
**même** AsyncConnection — donc la même transaction. La sémantique
actuelle de `async with get_sa_connection() as conn:` est préservée.

## Phasage

### Phase 1 — Fondation

- [x] Décision actée (cf. `audit-cto.md`)
- [x] Factories `Depends` dans `async_deps.py` pour les 9 repos qui
  ont déjà un port *(commit `d522b5f`)* + helper `db_conn` (Async
  Connection partagée par toutes les deps de la requête, FastAPI
  cache → même transaction).

### Phase 2 — Migration des routers, par lot

Chaque router = 1 commit. Indépendants entre eux.

Routers triés par taille (du plus petit au plus gros) pour valider le
pattern progressivement :

- [x] `publishers.py` *(commit `b617757`, pilote)*
- [x] `journals.py` *(commit `9ce5ee8`)*
- [x] `subjects.py` *(commit `a210947`)*
- [x] `addresses.py` *(commit `1bdb3dd`)*
- [x] `admin_feedback.py` *(commit `4a19525`)*
- [x] `admin_person_duplicates.py` *(commit `af657f9`)*
- [x] `admin_duplicates.py` *(commit `536122b`)*
- [x] `hal_problems.py` *(commit `e0cf5d6`)*
- [x] `config.py` *(commit `59a4181`)*
- [x] `perimeters.py` *(commit `b930093`)*
- [x] `structures.py` *(commit `291cbe3`)*
- [x] `stats.py` *(commit `c882221`)*
- [x] `laboratories.py` *(commit `48e618e`)*
- [x] `publications.py` *(commit `7b354b3`)*
- [x] `persons.py` (le plus gros — ~30 endpoints) *(commit `1c11602`)*

### Phase 3 — Query services manquants

Certains routers utilisent des query modules qui n'ont pas de port.
À créer au fur et à mesure de la migration des routers :

- [x] `subjects` query service *(commit `a210947`)*
- [x] `admin_feedback` query service *(commit `4a19525`)*
- [x] `hal_problems` query service *(commit `e0cf5d6`, inclut `hal_duplicate_accounts` déplacée depuis persons/admin)*
- [x] `publication_duplicates` query service *(commit `536122b`)*
- [x] `person_duplicates` query service *(commit `af657f9`)*
- [x] `publishers` query service *(commit `b617757`)*
- [x] `journals` query service *(commit `9ce5ee8`)*
- [x] `structures` query service *(commit `291cbe3`)*
- [x] `addresses` query service *(commit `1bdb3dd`)*
- [x] `laboratories` query service *(commit `48e618e`)*
- [x] `stats` query service *(commit `c882221` — agrège les 7 fonctions des 4 modules `stats/*` derrière `PgAsyncStatsQueries`)*
- [x] `publications` query service (list, facets, detail, all_years) *(commit `7b354b3`)*
- [x] `persons` query service (list, facets, directory, detail, admin) *(commit `1c11602`)*
- [x] `config` query service *(commit `59a4181`, inclut `get_hal_collections` migré depuis app_config.py)*

Chaque port = `Protocol` dans `application/ports/`. Implémentation =
classe wrapper dans `infrastructure/db/queries/` qui délègue aux
fonctions libres existantes (pas de réécriture du SQL).

### Phase 4 — Verrouillage

- [x] Durcir `import-linter` : contrat `forbidden` "Routers : pas
  d'import direct de infrastructure" ajouté dans `pyproject.toml` avec
  `allow_indirect_imports = "true"` (le chemin légitime
  `routers → async_deps → infrastructure` est préservé). Trois
  exceptions documentées : `auth.py → infrastructure.settings`,
  `admin_pipeline.py → infrastructure.pipeline_status`,
  `docs.py → infrastructure` (chemin projet) — aucune n'est une
  query/repo.
- [x] Mettre à jour `architecture.md` : règle 4 reformulée en
  "verrouillée par import-linter côté API" + liste des 3 exceptions.
- [x] Cocher dans `audit-cto.md` (Phase 2, item §1.6) et reformuler
  ROADMAP §1.6 en "terminé".

## Hors scope

- **CLI scripts** (`interfaces/cli/*`). Le tri (obsolètes vs vivants)
  est un préalable, à traiter dans un chantier séparé.
- **Tests unit sur routers via `dependency_overrides`**. Le bénéfice
  est ouvert mais l'exécution n'est pas dans ce chantier — la
  stratégie test reste end-to-end intégration tant qu'aucun besoin
  unit ne se présente.

## Validation

Critères pour considérer un router comme migré :

- Plus aucun import direct de `infrastructure.*` dans le fichier
  router.
- Tous les endpoints reçoivent leurs dépendances via `Depends(...)`.
- Tests d'intégration verts (`pytest tests/integration/interfaces/`).
- mypy passe sans nouveau `ignore`.
