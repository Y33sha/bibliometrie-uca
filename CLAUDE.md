# Consignes pour Claude Code

## Comportement attendu

### Code

- Privilégier les solutions **architecturalement propres** même si elles impliquent plus de fichiers modifiés. Avant d'appliquer un fix local, toujours vérifier si le problème est structurel.
- **Don't Repeat Yourself.** Si une modification touche plusieurs endroits dupliqués, signaler la duplication comme un problème à résoudre *avant* de modifier.
- Si des tests échouent ou si des problèmes sont détectés en passant, sans rapport avec le chantier en cours: au prochain commit, interrompre le chantier et traiter le problème. S'il est trop gros pour être traité en passant, le signaler comme chantier à planifier.

### Documentation, docstrings et commentaires

#### Contenu

- Dire ce que le code **fait**. Pas ce qu'il ne fait pas (ou ne fait plus).
- **Supprimer les affirmations devenues fausses.** Rectifier seulement si l'information est **indispensable** à cet endroit.
- **Rester factuel.** La documentation ne doit pas plaider ni argumenter.
- Viser la **concision maximale**. Adapter le niveau de détail à ce qui est strictement nécessaire à cet endroit. Lorsqu'un point devient non pertinent, corriger **en supprimant** le point plutôt qu'en soulignant sa non-pertinence ("ce n'est pas X mais Y…").

#### Style
- Utiliser le **présent intemporel**: ne jamais supposer connu l'état antérieur du code. Bannir tout vocabulaire ancré temporellement (`nouveau`, `désormais`, `ne plus`...). Ne jamais renvoyer à des fichiers transitoires (todo, roadmaps).
- Ecrire d'une manière intelligible hors contexte des conversations; **éviter le jargon** interne au projet et les abréviations maison (`SP` pour source_publication, `pub` pour publication...).
- **Ecrire des phrases courtes.** Pour lier les idées: parataxe > coordination (lorsque nécessaire) > subordination (à éviter). "ce qui explique que" => "donc"
- **Eviter les redondances.** Quand une phrase a deux parties séparées par deux-points, supprimer l'une des deux si elle ne fait que reformuler ou annoncer l'autre.
- **Préférer l'affirmation à la négation.** Dire "seul, seulement" au lieu de "ne... que". Eviter les doubles négations.
- **Un mot par notion.** Ne pas chercher l'élégance littéraire. Ne pas varier le vocabulaire pour éviter une répétition.
- **Eviter les termes imagés.** Toujours désigner les choses par leur nom.
- **Simplicité et précision.** Remplacer les mots vagues par des équivalents précis et univoques :
    * "la source atteste d'un document" => "le document est présent dans la source"
    * "la source ignore le document" => "le document est absent de la source"
    * "documents que leur source ne rend plus" => "documents disparus de leur source"
- Ne pas sur-franciser. Les anglicismes sont souhaitables s'ils sont usuels dans le domaine. (*repository* et non "dépôt"...) Eviter les anglicismes inintelligibles ("keyé", "retriable") ou superflus (quand des termes français usuels existent).

#### Orthographe et mise en page
- Respecter l'accentuation du français.
- Eviter les retours à la ligne non sémantiques (i.e. hors titres, listes et sauts de paragraphe).

### Savoir-vivre

- En fin de message, **proposer des pistes pour la suite** ou **attendre des instructions**. Ne pas suggérer de s'arrêter là, de faire une pause ou demander si l'utilisatrice veut continuer.
- Pour les décisions structurantes (impact sur le schéma de données ou la logique du pipeline), **attendre la décision** de l'utilisatrice avant de commencer à coder.
- Pas de mur de texte dans la conversation. Si tu dois cartographier le code avant de répondre, garde l'analyse pour toi, ou propose de générer un bilan au format *.md.
- **Vérifie** ce que tu affirmes.
- Ne propose **pas de pseudo-choix** idiots (ex. deux options dont seulement une respecte la cible; ou des alternatives sur l'ordre des opérations, si l'ordre est indifférent et que le phasage est déjà posé). Les alternatives creuses polluent la conversation et font perdre du temps.

### Workflow

- Pose tes questions en **texte libre**. Pas de QCM à choix limités.
- Gère les **commits** git. Fais un commit à chaque changement cohérent (au minimum une fois par phase de chantier, voire à chaque item d'une phase).
- Ne fais pas tourner la suite pytest plusieurs fois juste pour récupérer le résumé. Si c'est vert la première fois, c'est bon. Si tu veux le résumé, débrouille-toi pour le récupérer du premier coup, au lieu de tronquer l'output sans nécessité.

## Phases du pipeline

A jour au 2026-09-06

`extract` — Extraction HAL/OpenAlex/WoS/ScanR/theses
`resolve_ra` — Résolution Registration Agency des DOI
`fetch_missing` — Rattrapage cross-source (hal-id, NNT, DOI)
`fetch_stale` — Rafraîchissement des docs stale
`fetch_truncated` — Re-fetch OpenAlex tronqués (100 auteurs)
`normalize` — Normalisation staging → source_publications, source_authorships, addresses
`affiliations` — Résolution adresses → structures UCA
`publishers_journals` — Enrichissement journals (DOI, APC, DOAJ)
`metadata_correction` — Corrections métadonnées
`publications` — Création/rattachement publications
`persons` — Création personnes
`authorships` — Construction de la table consolidée
`relations` — Relations sémantiques entre publications
`subjects` — Sujets/mots-clés
`countries` — Détection pays
`oa_status` — Statut open access

Les quatre dernières sont des enrichissements, hors résolution d'entités : `--no-extras` les omet.

## Conventions du projet

- Nom de la base: `bibliometrie`
- Dépendances et contrats d'import: `pyproject.toml`
- Pre-commit hooks: `.pre-commit-config.yaml`
- CI: `.github/workflows/ci.yml`
- Documentation du projet: `/docs/`
- Chantiers en cours: `/docs/chantiers/`; chantiers archivés dans `/docs/chantiers/archived`. Structure: Contexte / Décisions / Phasage / Questions ouvertes. Phasage = sous-titres par phase et listes d'items à cocher.
- Architecture en couches DDD : `domain/` (règles et value objects, zéro I/O), `application/` (services dans `application/services/`, orchestrateurs du pipeline dans `application/pipeline/`), `infrastructure/` (adaptateurs SQL, APIs sources, settings), `interfaces/` (adaptateurs entrants : `interfaces/api/` pour FastAPI, `interfaces/frontend/` pour SvelteKit, `interfaces/cli/` pour les scripts et l'orchestrateur du pipeline).
- Frontend : SvelteKit (Svelte 5), routes dans `interfaces/frontend/src/routes/`
- Pipeline : phases dans `application/pipeline/`, extracteurs dans `infrastructure/sources/`, orchestrateur `interfaces/cli/run_pipeline.py`, installé comme commande `run_pipeline`
- Migrations Alembic dans `alembic/versions/` (créer : `alembic revision --autogenerate -m "..."` ; appliquer : `alembic upgrade head` ; rollback : `alembic downgrade -1`). Snapshot `infrastructure/db/schema.sql` régénéré par `python -m interfaces.cli.dev.dump_schema`.
- Tests backend : `python -m pytest tests/ -v` (nécessite `export DB_OWNER_PASSWORD=...`)
- Tests frontend : `cd interfaces/frontend && npm run check` (svelte-check, échoue sur les erreurs de types)
- Lancement dev : `bash start.sh` (uvicorn port 8000 + vite port 5173)
- Envoi de la branche : `ship`, fonction shell du poste (`~/.bashrc`), rebase sur `master`, pousse, ouvre la pull request et arme la fusion automatique en rebase. Le push déclenche les contrôles pre-push.
- Logging : utiliser `infrastructure/observability/log.py`
