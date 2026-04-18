# Consignes pour Claude Code

## Approche de développement

- A choisir entre "le plus propre" et "le plus rapide": toujours choisir le plus propre.
- Privilégier les solutions architecturalement propres même si elles impliquent plus de fichiers modifiés. Ne jamais appliquer de fix local sans vérifier si le problème est structurel. Demander confirmation avant de choisir une approche quick-fix.
- Ne pas proposer de pauses ou demander si l'utilisatrice veut continuer — elle le dira d'elle-même.
- Ne pas qualifier les tâches de "pas urgentes" — prioriser en fonction de l'impact sur le code, pas sur les données.
- Ne rien supposer. Vérifier.

## Conventions du projet

- Backend : FastAPI (Python), base PostgreSQL. Architecture en couches DDD : routers dans `backend/routers/`, services applicatifs (orchestration métier) dans `application/`, repositories SQL dans `infrastructure/repositories/`, value objects et règles métier dans `domain/`, utilitaires dans `utils/`
- Frontend : SvelteKit (Svelte 5), routes dans `frontend/src/routes/`
- Pipeline : scripts dans `processing/` et `extraction/`, orchestrateur `run_pipeline.py`
- Migrations SQL dans `db/migrations/`, appliquées via `python db/migrate.py`
- Tests backend : `python -m pytest tests/ -v` (nécessite `export DB_PASSWORD=...`)
- Tests frontend : `cd frontend && npm run check` (svelte-check, échoue sur les erreurs de types)
- Lancement dev : `bash start.sh` (uvicorn port 8003 + vite port 5176)
- Endpoints POST/PUT/PATCH : toujours un modèle Pydantic dans `backend/models.py`, jamais `body: dict`
- Requêtes SQL : toujours des requêtes paramétrées (`%s`), jamais d'interpolation f-string pour les valeurs
- Logging : utiliser `setup_logger` de `utils/log.py`
- DOI : utiliser `clean_doi` de `utils/doi.py`
- Noms : utiliser `names_compatible` et `parse_raw_author_name` de `utils/names.py`
