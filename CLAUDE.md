# Consignes pour Claude Code

## Approche de développement

- Privilégier les solutions architecturalement propres même si elles impliquent plus de fichiers modifiés. Ne jamais appliquer de fix local sans vérifier si le problème est structurel. Demander confirmation avant de choisir une approche quick-fix.
- Ne pas proposer de pauses ou demander si l'utilisatrice veut continuer — elle le dira d'elle-même.
- Ne pas qualifier les tâches de "pas urgentes" — prioriser en fonction de l'impact sur le code, pas sur les données.

## Conventions du projet

- Backend : FastAPI (Python), base PostgreSQL, modules dans `backend/routers/`, services dans `services/`, utilitaires dans `utils/`
- Frontend : SvelteKit (Svelte 5), routes dans `frontend/src/routes/`
- Pipeline : scripts dans `processing/` et `extraction/`, orchestrateur `run_pipeline.py`
- Migrations SQL dans `db/migrations/`, appliquées via `python db/migrate.py`
- Tests : `python -m pytest tests/ -v` (nécessite `export DB_PASSWORD=...`)
- Lancement dev : `bash start.sh` (uvicorn port 8003 + vite port 5176)
- Logging : utiliser `setup_logger` de `utils/log.py`
- DOI : utiliser `clean_doi` de `utils/doi.py`
- Noms : utiliser `names_compatible` et `parse_raw_author_name` de `utils/names.py`
