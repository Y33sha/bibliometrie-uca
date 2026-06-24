# Consignes pour Claude Code

## Approche de développement

### Code

- Privilégier les solutions architecturalement propres même si elles impliquent plus de fichiers modifiés. Ne jamais appliquer de fix local sans vérifier si le problème est structurel. Demander confirmation avant de choisir une approche quick-fix.
- Avant toute proposition de modification du schéma de données: consulter le schéma existant.
- Si des tests échouent ou si des problèmes sont détectés en passant, sans être liés au chantier en cours: au prochain commit, interrompre le chantier et s'occuper du problème. S'il est trop gros pour être traité en passant, le signaler comme futur chantier.

### Documentation et commentaires

- Respecter l'accentuation du français.
- Toujours utiliser le présent intemporel pour la documentation et les commentaires: ne jamais supposer connu l'état passé du code.
- Ecrire la documentation et les commentaires d'une manière intelligible pour quelqu'un qui n'a pas le contexte des conversations: éviter le jargon interne au projet.
- Eviter les sauts de ligne non sémantiques.

### Savoir-vivre

- En fin de message, proposer des pistes pour la suite. Ne pas proposer de pauses ou demander si l'utilisatrice veut continuer.
- Pour les décisions structurantes (impact sur le schéma de données, la logique du pipeline, l'UI), toujours attendre la décision de l'utilisatrice avant de commencer à coder.
- Ne pas faire tourner la suite pytest plusieurs fois juste pour récupérer le résumé. Si c'est vert la première fois, c'est bon. Si tu veux le résumé, débrouille-toi pour le récupérer du premier coup, au lieu de tronquer l'output sans nécessité.

## Conventions du projet

- Chantiers en cours: `/docs/chantiers/`; chantiers archivés dans `/docs/chantiers/archived`.
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
