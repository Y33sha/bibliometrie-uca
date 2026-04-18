# Bibliométrie UCA

Suivi de la production scientifique de l'Université Clermont Auvergne.
Intègre trois sources bibliographiques (HAL, OpenAlex, Web of Science) dans un
référentiel dédupliqué de publications, personnes et laboratoires.

## Stack technique

- **Frontend** : SvelteKit (Svelte 5) — `interfaces/frontend/`
- **Backend** : FastAPI + PostgreSQL (psycopg2) — `backend/`
- **Pipeline** : scripts Python — `processing/`, `extraction/`
- **Base de données** : PostgreSQL 18

## Prérequis

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)

Ou, pour une installation sans Docker :

- Python 3.10+
- Node.js 20+ / npm 10+
- PostgreSQL 18+ avec extensions `pg_trgm`, `unaccent`

## Installation avec Docker (recommandé)

### 1. Configuration

```bash
cp .env.example .env
```

Editer `.env` avec vos valeurs (credentials DB, admin, clés API).

### 2. Lancement (dev)

```bash
docker compose up
```

- Frontend : http://localhost:5176/bibliometrie
- Backend / API : http://localhost:8003

Le code est monté en volume : les modifications sont prises en compte en temps réel (hot reload backend + frontend).

### 3. Importer une base existante

```bash
# Copier le dump dans le conteneur
docker cp bibliometrie.dump bibliometrie-uca-db-1:/tmp/

# Restaurer
docker compose exec db bash -c "pg_restore -U lalecoz -d bibliometrie --no-owner -j 4 /tmp/bibliometrie.dump"
```

Pour créer une base vide à la place :

```bash
docker compose exec db psql -U postgres -d bibliometrie -f /app/db/schema.sql
```

### 4. Pipeline de données

```bash
docker compose exec backend python run_pipeline.py
```

### 5. Lancement (prod)

En production, le backend sert l'API et le frontend buildé (image unique) :

```bash
docker compose -f docker-compose.prod.yml up -d
```

### Commandes utiles

```bash
docker compose down        # Arrêter les conteneurs
docker compose down -v     # Arrêter et supprimer le volume PostgreSQL
docker compose logs -f     # Suivre les logs
docker compose exec backend bash   # Shell dans le conteneur backend
```

## Installation sans Docker

### Base de données

```bash
createdb bibliometrie
psql -d bibliometrie -f db/schema.sql
python db/migrate.py
```

Deux options pour initialiser les données :

**Option A — Restaurer un dump complet** (base existante) :
```bash
pg_restore -U lalecoz -d bibliometrie --clean --if-exists bibliometrie.dump
```

**Option B — Démarrer de zéro** (seed minimal) :
```bash
psql -d bibliometrie -f db/seed.sql
```
Le seed contient les données de référence (structures, relations, pays, config).
Les credentials API (clés WoS, ScanR, etc.) sont remplacés par des placeholders :
les renseigner dans la table `config` avant de lancer le pipeline.

Pour régénérer le seed depuis une base existante : `python scripts/generate_seed.py`

### Backend

```bash
pip install ".[dev]"   # runtime + outils de dev (pytest, ruff, mypy, …)
# ou, pour un déploiement sans dev tools :
pip install .

# Installer le hook pre-commit (lance ruff + checks YAML/TOML avant chaque commit)
pre-commit install
```

### Frontend

```bash
cd interfaces/frontend
npm install
```

## Lancement sans Docker

### Développement

```bash
# Backend (port 8003 par défaut)
uvicorn interfaces.api.app:app --reload

# Frontend (port 5173 par défaut)
cd frontend && npm run dev
```

### Production

```bash
# Build du frontend
cd frontend && npm run build

# Backend via pm2
pm2 start backend/app.py --name bibliometrie --interpreter python3
```

Voir [docs/deploiement](memory/reference_deployment.md) pour la configuration
nginx et pm2.

## Pipeline de données

```bash
# Pipeline complet
python run_pipeline.py

# Reprise à partir d'une phase
python run_pipeline.py --from persons

# Une seule phase
python run_pipeline.py --only authorships

# Dry-run
python run_pipeline.py --dry-run

# Lister les phases disponibles
python run_pipeline.py --list
```

Voir [docs/pipeline.md](docs/pipeline.md) pour le détail des 9 phases.

## Tests

```bash
python -m pytest tests/ -v
```

Les tests d'intégration utilisent une base `bibliometrie_test` créée
automatiquement.

## Arborescence

```
bibliometrie-uca/
├── backend/              API FastAPI
│   ├── app.py            Point d'entrée
│   ├── routers/          Endpoints par domaine
│   ├── deps.py           Dépendances (connexion DB, auth)
│   ├── filters.py        Filtres SQL partagés
│   └── models.py         Modèles Pydantic
├── interfaces/frontend/             Application SvelteKit
│   └── src/
│       ├── routes/       Pages (publiques + admin)
│       └── lib/          Composants et styles partagés
├── processing/           Scripts du pipeline
├── extraction/           Moissonnage des sources
│   ├── hal/
│   ├── openalex/
│   └── wos/
├── services/             Logique métier (persons, authorships, publications, journals)
├── db/                   Schéma SQL, connexion, scripts SQL
├── scripts/              Scripts manuels (imports, corrections)
├── tests/                Tests (pytest)
├── utils/                Utilitaires partagés (normalisation)
├── config/               Configuration (settings.py)
├── run_pipeline.py       Orchestrateur du pipeline
└── docs/                 Documentation
    ├── architecture.md   Schéma, principes de conception, tables
    ├── pipeline.md       Pipeline détaillé (11 phases)
    ├── sources.md        Sources de données (API, imports, particularités)
    ├── exploitation.md   Guide d'exploitation (lancement, reprise, supervision)
    ├── glossaire.md      Termes métier
    └── guide-utilisateur.md  Fonctionnalités de l'application
```

## Documentation

- [Architecture des données](docs/architecture.md) — schéma, principes de conception, diagramme ER
- [Pipeline](docs/pipeline.md) — les 11 phases de traitement, utilitaires partagés
- [Sources de données](docs/sources.md) — API, imports manuels, particularités de chaque source
- [Guide d'exploitation](docs/exploitation.md) — lancement du pipeline, reprise, supervision, limites connues
- [Glossaire](docs/glossaire.md) — définitions des termes métier
- [Guide utilisateur](docs/guide-utilisateur.md) — pages et fonctionnalités de l'application
