# Bibliométrie UCA

Suivi de la production scientifique de l'Université Clermont Auvergne.
Intègre cinq sources bibliographiques (HAL, OpenAlex, Web of Science,
ScanR, theses.fr) dans un référentiel dédupliqué de publications,
personnes et laboratoires.

## Stack technique

- **Frontend** : SvelteKit (Svelte 5) — `interfaces/frontend/`
- **Backend** : FastAPI + PostgreSQL 18 (psycopg2) — `interfaces/api/`
- **Pipeline** : Python — `application/pipeline/` (orchestrateur
  `run_pipeline.py`), extracteurs dans `infrastructure/sources/`
- **Architecture** : DDD en 4 couches (`domain/`, `application/`,
  `infrastructure/`, `interfaces/`) — voir
  [docs/architecture.md](docs/architecture.md) (archi logicielle) et
  [docs/donnees.md](docs/donnees.md) (modèle de données)

## Prérequis

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (recommandé)

Ou, installation sans Docker :
- Python 3.10+
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
docker compose exec db bash -c "pg_restore -U lalecoz -d bibliometrie --no-owner -j 4 /tmp/bibliometrie.dump"
```

Ou créer une base vide :

```bash
docker compose exec db psql -U postgres -d bibliometrie -f /app/infrastructure/db/schema.sql
docker compose exec backend python -m infrastructure.db.migrate
```

### 4. Pipeline

```bash
docker compose exec backend python run_pipeline.py
```

### 5. Production

```bash
docker compose -f docker-compose.prod.yml up -d
```

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
psql -d bibliometrie -f infrastructure/db/schema.sql
python -m infrastructure.db.migrate
```

Deux options pour initialiser les données :

**Option A — Restaurer un dump complet** :
```bash
pg_restore -U lalecoz -d bibliometrie --clean --if-exists bibliometrie.dump
```

**Option B — Démarrer de zéro** :
```bash
psql -d bibliometrie -f infrastructure/db/seed.sql
```
Le seed contient les données de référence (structures, relations, pays,
config). Les credentials API sont des placeholders : à renseigner dans
la table `config` avant le pipeline.

Pour régénérer le seed depuis une base existante :
`python interfaces/cli/generate_seed.py`.

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

```bash
# Build frontend
cd interfaces/frontend && npm run build

# Backend via pm2
pm2 start interfaces/api/app.py --name bibliometrie --interpreter python3
```

Voir [docs/exploitation.md](docs/exploitation.md) pour nginx et pm2.

## Pipeline de données

```bash
python run_pipeline.py                    # Complet (9 phases)
python run_pipeline.py --from persons     # Reprise depuis une phase
python run_pipeline.py --only authorships # Une seule phase
python run_pipeline.py --list             # Liste des phases
python run_pipeline.py --dry-run          # Sans exécuter
python run_pipeline.py --mode weekly      # Import hebdomadaire (WoS exclu)
python run_pipeline.py --sources hal,openalex  # Sources spécifiques
```

Voir [docs/pipeline.md](docs/pipeline.md) pour le détail des 9 phases.

## Tests

```bash
export DB_PASSWORD=...                      # Requis pour les tests d'intégration
python -m pytest tests/ -v                  # Tout
python -m pytest tests/unit/ -q             # Unitaires seuls (~1s)
python -m pytest tests/integration/ -q      # Intégration (~10s, base bibliometrie_test)
python -m pytest tests/ --cov               # Avec couverture (seuil 49%)
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
│   ├── db/              Schéma SQL, migrations, query services
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
- [Pipeline](docs/pipeline.md) — les 9 phases de traitement
- [Sources de données](docs/sources.md) — API, imports manuels, particularités par source
- [Guide d'exploitation](docs/exploitation.md) — lancement, reprise, supervision, déploiement
- [Glossaire](docs/glossaire.md) — définitions des termes métier
- [Guide utilisateur](docs/guide-utilisateur.md) — pages et fonctionnalités

## Roadmap

Voir [ROADMAP.md](ROADMAP.md) pour l'état des chantiers (architecture,
qualité, documentation) et la liste des points d'audit périodique.
