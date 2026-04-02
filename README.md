# Bibliométrie UCA

Suivi de la production scientifique de l'Université Clermont Auvergne.
Intègre trois sources bibliographiques (HAL, OpenAlex, Web of Science) dans un
référentiel dédupliqué de publications, personnes et laboratoires.

## Stack technique

- **Frontend** : SvelteKit (Svelte 5) — `frontend/`
- **Backend** : FastAPI + PostgreSQL (psycopg2) — `backend/`
- **Pipeline** : scripts Python — `processing/`, `extraction/`
- **Base de données** : PostgreSQL 18

## Prérequis

- Python 3.10+
- Node.js 20+ / npm 10+
- PostgreSQL 18+
- Extension PostgreSQL : `pg_trgm`, `unaccent`

## Installation

### Base de données

```bash
createdb bibliometrie
psql -d bibliometrie -f db/schema.sql
```

### Backend

```bash
pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

## Lancement

### Développement

```bash
# Backend (port 8000 par défaut)
uvicorn backend.app:app --reload

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
├── frontend/             Application SvelteKit
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
    ├── glossaire.md      Termes métier
    ├── pipeline.md       Pipeline détaillé
    └── guide-utilisateur.md  Fonctionnalités de l'application
```

## Documentation

- [Architecture des données](ARCHITECTURE.md) — schéma, principes de conception, tables
- [Glossaire](docs/glossaire.md) — définitions des termes métier
- [Pipeline](docs/pipeline.md) — les 9 phases de traitement
- [Guide utilisateur](docs/guide-utilisateur.md) — pages et fonctionnalités de l'application
