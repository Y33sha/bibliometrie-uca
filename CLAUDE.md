# Consignes pour Claude Code

## Approche de développement

- Privilégier les solutions architecturalement propres même si elles impliquent plus de fichiers modifiés. Ne jamais appliquer de fix local sans vérifier si le problème est structurel. Demander confirmation avant de choisir une approche quick-fix.
- Ne pas proposer de pauses ou demander si l'utilisatrice veut continuer — elle le dira d'elle-même.
- Avant toute proposition de modification du schéma de données: consulter le schéma existant.
- Ne jamais écrire de commentaires faisant référence à des fichiers transitoires (todo, roadmap) ou à un état passé du code.
- Si des tests échouent sans être liés au chantier en cours: au prochain commit, interrompre le chantier et s'occuper du problème.
- Ne jamais proposer de faire une pause.

## Conventions du projet

- Architecture en couches DDD : `domain/` (règles et value objects, zéro I/O), `application/` (orchestrateurs métier, incluant `application/pipeline/`), `infrastructure/` (adapters SQL, APIs sources, settings), `interfaces/` (adapters entrants : `interfaces/api/` pour FastAPI, `interfaces/frontend/` pour SvelteKit, `interfaces/cli/` pour les scripts one-shot). Entry points CLI : `run_pipeline.py` à la racine.
- Frontend : SvelteKit (Svelte 5), routes dans `interfaces/frontend/src/routes/`
- Pipeline : phases dans `application/pipeline/`, extracteurs dans `infrastructure/sources/`, orchestrateur `run_pipeline.py` à la racine
- Migrations Alembic dans `alembic/versions/` (créer : `alembic revision --autogenerate -m "..."` ; appliquer : `alembic upgrade head` ; rollback : `alembic downgrade -1`). Snapshot `infrastructure/db/schema.sql` régénéré par `python -m infrastructure.db.dump_schema`.
- Tests backend : `python -m pytest tests/ -v` (nécessite `export DB_PASSWORD=...`)
- Tests frontend : `cd interfaces/frontend && npm run check` (svelte-check, échoue sur les erreurs de types)
- Lancement dev : `bash start.sh` (uvicorn port 8003 + vite port 5176)
- Endpoints POST/PUT/PATCH : toujours un modèle Pydantic dans `interfaces/api/models.py`, jamais `body: dict`
- Requêtes SQL : toujours des requêtes paramétrées (`%s`), jamais d'interpolation f-string pour les valeurs
- Logging : utiliser `setup_logger` de `infrastructure/log.py`
- DOI : utiliser `DOI` / `DOI.try_parse` de `domain/publication.py` ; `clean_doi` de `utils/doi.py` reste un shim pour le code existant
- Noms : utiliser `names_compatible` et `parse_raw_author_name` de `domain/names.py`
