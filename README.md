# Bibliométrie UCA

Suivi de la production scientifique de l'Université Clermont Auvergne.

Le pipeline collecte auprès de sources en ligne les métadonnées de publications scientifiques rattachées à l'université, les dédoublonne et les relie à leurs auteurs et structures de rattachement. L'application web les restitue sous forme de listes et de tableaux de bord.

## Stack technique

- **Frontend** : SvelteKit (Svelte 5) — `interfaces/frontend/`
- **Backend** : FastAPI + PostgreSQL 18 (SQLAlchemy) — `interfaces/api/`
- **Pipeline** : Python — paquet `pipeline/` (orchestrateur `pipeline/run.py`, commande `run_pipeline`)
- **Architecture** : DDD en 4 couches (`domain/`, `application/`, `infrastructure/`, `interfaces/`), pipeline hors des couches

## Démarrer

Prérequis : Docker et le plugin Compose.

- **Linux** : Docker Engine + plugin Compose via le [dépôt officiel](https://docs.docker.com/engine/install/).
- **macOS** : [Docker Desktop](https://www.docker.com/products/docker-desktop/).
- **Windows** : [Docker Desktop](https://www.docker.com/products/docker-desktop/) avec le backend WSL2.

```bash
cp .env.example .env    # puis renseigner les variables
docker compose up
```

- Frontend : <http://localhost:5173/bibliometrie>
- API : <http://localhost:8000>

L'application a besoin d'une base initialisée : la marche à suivre, du `.env` aux rôles de connexion, est dans [Développement local](docs/exploitation/01-developpement-local.md). Pour un déploiement, voir [Production](docs/exploitation/02-production.md), et pour remplir la base, [Pipeline](docs/exploitation/03-pipeline.md).

## Arborescence

```
bibliometrie-uca/
├── domain/              Entités, value objects, règles pures (zéro I/O)
├── application/         Écritures de l'administration
│   ├── services/        Services d'écriture appelés par l'API
│   └── ports/           Interfaces que l'infrastructure implémente
├── infrastructure/      Adaptateurs sortants
│   ├── db/              Schéma SQL, MetaData SA, engine
│   ├── repositories/    Lecture et écriture des entités du domaine
│   ├── read_models/     Projections de lecture pour l'API
│   └── raw_store/       Archivage des réponses brutes des sources
├── interfaces/          Adaptateurs entrants
│   ├── api/             FastAPI (routers, models Pydantic, middlewares)
│   ├── frontend/        SvelteKit
│   └── cli/             Imports, maintenance
├── pipeline/            Pipeline (orchestrateur run.py)
│   ├── ingestion/       Moissonnage et normalisation par source (hal, openalex, wos, scanr, theses…)
│   ├── transformation/  Transformation par domaine (structures, publishing, publications, persons)
│   └── runtime/         Contexte d'exécution des phases, observabilité
├── alembic/             Migrations
├── tests/               pytest (unit + integration)
└── docs/                Documentation
```

## Documentation

- [Guide d'exploitation](docs/exploitation/) — développement local, production, pipeline
- [Architecture](docs/architecture/) — couches DDD, ports/adaptateurs, règles d'import
- [Modèle de données](docs/donnees/) — une page par entité, index des tables
- [Pipeline](docs/pipeline/) — les phases de traitement
- [Sources de données](docs/sources/) — API, imports manuels, particularités par source
- [Guide utilisateur](docs/guide-utilisateur/) — pages publiques, pages admin, workflows
- [Glossaire](docs/glossaire.md) — définitions des termes métier

La documentation se lit aussi comme un site, avec la référence du code générée depuis les docstrings : `uv run zensical serve`.
