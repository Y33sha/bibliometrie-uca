# Bibliométrie UCA

Suivi de la production scientifique de l'Université Clermont Auvergne.
Intègre cinq sources bibliographiques (HAL, OpenAlex, Web of Science,
ScanR, theses.fr) dans un référentiel dédupliqué de publications,
personnes et laboratoires.

## Stack technique

- **Frontend** : SvelteKit (Svelte 5) — `interfaces/frontend/`
- **Backend** : FastAPI + PostgreSQL 18 (SQLAlchemy) — `interfaces/api/`
- **Pipeline** : Python — `application/pipeline/` (orchestrateur
  `run_pipeline.py`), extracteurs dans `infrastructure/sources/`
- **Architecture** : DDD en 4 couches (`domain/`, `application/`,
  `infrastructure/`, `interfaces/`) — voir
  [docs/architecture.md](docs/architecture.md) (archi logicielle) et
  [docs/donnees.md](docs/donnees.md) (modèle de données)

## Prérequis

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (recommandé)

Ou, installation sans Docker :
- Python 3.12+
- Node.js 20+ / npm 10+
- PostgreSQL 18+ avec extensions `pg_trgm`, `unaccent`
- [`uv`](https://docs.astral.sh/uv/) recommandé pour l'install des deps

## Installation avec Docker (recommandé)

### 1. Configuration

```bash
cp .env.example .env
```

Éditer `.env` avec vos valeurs (credentials DB, admin, clés API).

### 2. Lancement (dev)

```bash
docker compose up
```

- Frontend : http://localhost:5176/bibliometrie
- API : http://localhost:8003

Le code est monté en volume : hot reload backend + frontend.

### 3. Importer une base existante

```bash
docker cp bibliometrie.dump bibliometrie-uca-db-1:/tmp/
docker compose exec db bash -c 'pg_restore -U "$POSTGRES_USER" -d bibliometrie --no-owner -j 4 /tmp/bibliometrie.dump'
```

Ou créer une base vide (le pipeline applique toutes les migrations<!--TODO: what?-->) :

```bash
docker compose exec backend alembic upgrade head
```

### 4. Pipeline

```bash
docker compose exec backend python run_pipeline.py
```

### 5. Production

```bash
docker compose -f docker-compose.prod.yml up -d
```

Différences avec le compose de dev : un seul conteneur applicatif (backend + frontend buildé en SPA statique, plus de vite dev server), pas de volume code, port DB non exposé. Voir [docs/exploitation/03-deploiement.md](docs/exploitation/03-deploiement.md) pour les détails et les options de déploiement hors Docker.

### Commandes utiles

```bash
docker compose down        # Arrêter les conteneurs
docker compose down -v     # + supprimer le volume PostgreSQL
docker compose logs -f     # Suivre les logs
docker compose exec backend bash   # Shell dans le conteneur backend
```

## Installation sans Docker

### Base de données

```bash
createdb bibliometrie
alembic upgrade head     # applique toutes les migrations
```

`schema.sql` est un snapshot descriptif (utile pour relire la
structure d'un coup d'œil), pas la source de vérité — la vérité, ce
sont les migrations Alembic dans `alembic/versions/`. Pour
rafraîchir le snapshot après une série de migrations :
`python -m infrastructure.db.dump_schema`.

Deux options pour initialiser les données :

**Option A — Restaurer un dump complet** :
```bash
pg_restore -U "$DB_USER" -d bibliometrie --clean --if-exists bibliometrie.dump
```

**Option B — Démarrer de zéro** :
```bash
psql -d bibliometrie -f infrastructure/db/seed.sql
```
Le seed contient les données de référence (structures, relations, pays,
config). Les credentials API sont des placeholders : à renseigner dans
la table `config` avant le pipeline.

Pour régénérer le seed depuis une base existante :
`python -m interfaces.cli.dev.generate_seed`.

### Backend

```bash
# Avec uv (recommandé)
uv sync

# Ou avec pip
pip install ".[dev]"   # runtime + dev tools (pytest, ruff, mypy, …)

# Hook pre-commit (ruff + mypy + lint-imports + pytest-unit)
pre-commit install
```

### Frontend

```bash
cd interfaces/frontend
npm install
```

## Lancement sans Docker

### Développement

Tout-en-un (backend port 8003 + frontend port 5176) :

```bash
bash start.sh
```

Ou séparément :

```bash
python -m uvicorn interfaces.api.app:app --reload --port 8003
cd interfaces/frontend && npm run dev -- --port 5176
```

### Production

Deux voies au choix :

- **Docker** (recommandé pour la prod) : `docker compose -f docker-compose.prod.yml up -d` — un conteneur applicatif autoportant (backend + frontend buildé en SPA statique) + un conteneur Postgres. Voir [docs/exploitation/03-deploiement.md](docs/exploitation/03-deploiement.md).
- **Sans Docker** : build du frontend (`cd interfaces/frontend && npm run build` — la SPA est ensuite servie par l'API), puis lancement d'uvicorn avec le gestionnaire de process de votre choix (systemd, supervisor, pm2…). Exemple uvicorn nu : `uvicorn interfaces.api.app:app --host 0.0.0.0 --port 8003`.

## Pipeline de données

```bash
python run_pipeline.py                    # Complet
python run_pipeline.py --from persons     # Reprise depuis une phase
python run_pipeline.py --only authorships # Une seule phase
python run_pipeline.py --list             # Liste des phases
python run_pipeline.py --dry-run          # Sans exécuter
python run_pipeline.py --mode weekly      # Import hebdomadaire (WoS exclu)
python run_pipeline.py --sources hal,openalex  # Sources spécifiques
```

Voir [docs/pipeline.md](docs/pipeline.md) pour le détail des phases.

## Tests

```bash
export DB_PASSWORD=...                      # Requis pour les tests d'intégration
python -m pytest tests/ -v                  # Tout
python -m pytest tests/unit/ -q             # Unitaires seuls (~1s)
python -m pytest tests/integration/ -q      # Intégration (~10s, base bibliometrie_test)
python -m pytest tests/ --cov               # Avec couverture (seuil 85%)
```

Les tests d'intégration utilisent une base `bibliometrie_test` créée
automatiquement.

## Arborescence

```
bibliometrie-uca/
├── domain/              Entités, value objects, règles pures (zéro I/O)
├── application/         Services métier, orchestrateurs
│   └── pipeline/        Phases du pipeline (normalize, build, enrich, …)
├── infrastructure/      Adapters sortants (SQL, API sources, settings)
│   ├── db/              Schéma SQL, MetaData SA, query services
│   ├── sources/         Extracteurs API (hal, openalex, wos, scanr, theses)
│   └── repositories/    Adapters PostgreSQL pour les ports domain/
├── interfaces/          Adapters entrants
│   ├── api/             FastAPI (routers, models Pydantic, middlewares)
│   ├── frontend/        SvelteKit
│   └── cli/             Scripts one-shot (imports, debug, corrections)
├── tests/               pytest (unit + integration)
├── logs/                Logs consolidés (JSON), status.json, rapports pipeline
├── run_pipeline.py      Orchestrateur du pipeline
├── start.sh             Lancement dev (backend + frontend)
└── docs/                Documentation
```

Voir [docs/architecture.md](docs/architecture.md) pour les règles
d'import entre couches (vérifiées par import-linter en pre-commit + CI).

## Documentation

- [Architecture logicielle](docs/architecture.md) — couches DDD, ports/adapters, règles d'import
- [Modèle de données](docs/donnees.md) — schéma, domaines fonctionnels, relations
- [Sources de données](docs/sources.md) — API, imports manuels, particularités par source
- [Pipeline](docs/pipeline.md) — les 9 phases de traitement
- [Guide d'exploitation](docs/exploitation/) — initialisation, déploiement, lancement, supervision
- [Guide utilisateur](docs/guide-utilisateur.md) — pages et fonctionnalités
- [Glossaire](docs/glossaire.md) — définitions des termes métier

## Chantiers

Les chantiers en cours et terminés sont documentés dans
[docs/chantiers/](docs/chantiers/). Chaque fiche porte un préfixe :
`METIER_` (nouvelles fonctionnalités, changements de comportement), `DATA_` (révision du schéma ou du traitement des données) ou `CODE_` (refactor / chantier qualité). Les fiches datées
correspondent aux chantiers terminés ; les fiches non datées sont en cours.
