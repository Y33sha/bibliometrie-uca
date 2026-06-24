# Consignes pour Claude Code

## Comportement attendu

### Code

- Privilégier les solutions architecturalement propres même si elles impliquent plus de fichiers modifiés. Avant d'appliquer un fix local, toujours vérifier si le problème est structurel.
- Si une modification touche plusieurs endroits dupliqués, signaler la duplication comme un problème à résoudre *avant* de modifier.
- Si des tests échouent ou si des problèmes sont détectés en passant, sans rapport avec le chantier en cours: au prochain commit, interrompre le chantier et traiter le problème. S'il est trop gros pour être traité en passant, le signaler comme chantier à planifier.

### Documentation et commentaires

- Toujours utiliser le présent intemporel: ne jamais supposer connu l'état antérieur du code. Bannir tout vocabulaire ancré temporellement (`nouveau`, `désormais`, `ne plus`...). Ne jamais renvoyer à des fichiers transitoires (todo, roadmaps).
- Ecrire d'une manière qui reste intelligible en dehors du contexte des conversations; éviter le jargon interne au projet et les abréviations maison (`SP` pour source_publication, `pub` pour publication...). Les anglicismes sont permis s'ils sont usuels dans le domaine.
- Au fil des réécritures, lorsqu'un point devient non pertinent, corriger en supprimant le point plutôt qu'en soulignant sa non-pertinence.
- Respecter l'accentuation du français.
- Eviter les retours à la ligne non sémantiques (i.e. hors titres, listes et sauts de paragraphe).

### Savoir-vivre

- En fin de message, proposer des pistes pour la suite ou attendre des instructions. Ne pas suggérer de s'arrêter là, de faire une pause ou demander si l'utilisatrice veut continuer.
- Pour les décisions structurantes (impact sur le schéma de données ou la logique du pipeline), toujours attendre la décision de l'utilisatrice avant de commencer à coder.
- Ne pas faire tourner la suite pytest plusieurs fois juste pour récupérer le résumé. Si c'est vert la première fois, c'est bon. Si tu veux le résumé, débrouille-toi pour le récupérer du premier coup, au lieu de tronquer l'output sans nécessité.

## Conventions du projet

- Dépendances et contrats d'import: `pyproject.toml`
- Pre-commit hooks: `.pre-commit-config.yaml`
- Documentation du projet: `/docs/`
- Chantiers en cours: `/docs/chantiers/`; chantiers archivés dans `/docs/chantiers/archived`.
- Architecture en couches DDD : `domain/` (règles et value objects, zéro I/O), `application/` (orchestrateurs métier, incluant `application/pipeline/`), `infrastructure/` (adapters SQL, APIs sources, settings), `interfaces/` (adapters entrants : `interfaces/api/` pour FastAPI, `interfaces/frontend/` pour SvelteKit, `interfaces/cli/` pour les scripts). Entry points CLI : `run_pipeline.py` à la racine.
- Frontend : SvelteKit (Svelte 5), routes dans `interfaces/frontend/src/routes/`
- Pipeline : phases dans `application/pipeline/`, extracteurs dans `infrastructure/sources/`, orchestrateur `run_pipeline.py` à la racine
- Migrations Alembic dans `alembic/versions/` (créer : `alembic revision --autogenerate -m "..."` ; appliquer : `alembic upgrade head` ; rollback : `alembic downgrade -1`). Snapshot `infrastructure/db/schema.sql` régénéré par `python -m infrastructure.db.dump_schema`.
- Tests backend : `python -m pytest tests/ -v` (nécessite `export DB_PASSWORD=...`)
- Tests frontend : `cd interfaces/frontend && npm run check` (svelte-check, échoue sur les erreurs de types)
- Lancement dev : `bash start.sh` (uvicorn port 8003 + vite port 5176)
- Endpoints POST/PUT/PATCH : toujours un modèle Pydantic dans `interfaces/api/models.py`, jamais `body: dict`
- Requêtes SQL : toujours des requêtes paramétrées (`%s`), jamais d'interpolation f-string pour les valeurs
- Logging : utiliser `setup_logger` de `infrastructure/log.py`
