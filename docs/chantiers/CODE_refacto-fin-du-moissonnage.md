# Chantier — Refactorisation : fin du moissonnage

## Contexte

Suite de la relecture du pipeline dans l'ordre d'exécution, selon *A Philosophy of Software Design* (John Ousterhout). La [fiche précédente](archived/2026-11-17_CODE_refacto-orchestrateur-et-moissonnage.md) couvre l'orchestrateur et la phase `harvest`.

## Décisions

- Périmètre de la fiche : phases `harvest_by_person`, `fetch_missing`, `fetch_stale`, `fetch_truncated`, et leurs modules communs dans `pipeline/ingestion/common/`.

## Phasage

### Phase 1 — Docstrings

- [x] `pipeline/ingestion/common/person_search.py` : la docstring du module renvoie à `SourceProfile.person_identifiers` au lieu de `PERSON_SEARCH_IDENTIFIERS`, absent du code.
- [x] `pipeline/ingestion/openalex/fetch_truncated.py` : suppression de la chaîne orpheline « Plafond OpenAlex 10 req/s. ».
- [x] `pipeline/ingestion/common/fetch_stale.py` : suppression de « ou `None` pour tout l'historique » dans la docstring de `_years`. `window_years` renvoie toujours une liste. Le paramètre `years` devient obligatoire dans `get_stale_source_ids`, `refresh`, `get_missing_dois` et `fetch_missing_doi`.
- [x] Les docstrings des phases perdent les redites de `Phase.when`, de la CLI et du profil de source : « sautée dans un mode dont la policy l'exclut », « `--sources` restreint les sources », « WoS est opt-in ».

### Phase 2 — Observabilité

- [x] Le `_summary` de `fetch_stale` compte `new` : documents renvoyés sous un autre identifiant natif. La table de la phase dans l'administration a sa colonne « Nouveaux ».
- [x] La ligne « Total » s'écrit seulement quand une phase de moissonnage a exécuté plusieurs tâches. Pour `fetch_truncated`, ou `harvest` restreint à une source, elle redit la ligne de bilan de l'unique tâche. Elle passe de `pipeline/run.py` à `run_phase`, qui connaît les tâches exécutées : une phase sautée perd sa ligne « Total : rien à faire ».

### Phase 3 — Canaux de `fetch_missing`

- [ ] Une dataclass de canal réunit le nom de la tâche, la source, le type d'identifiant affiché au journal, la clé d'observabilité et la phrase d'étape. L'ajout d'un canal touche un seul endroit, au lieu des constantes de nom, de `_BY_SOURCE`, de `_SUMMARIES` et de `_CHANNEL_KEYS`.

## Questions ouvertes

- Clés d'observabilité de `fetch_missing`, stockées dans `pipeline_phase_executions` : `"hal-id"` désigne la recherche par hal-id dans HAL, `"hal"` la recherche par DOI dans HAL. Des clés symétriques (`source` et type d'identifiant) changeraient la forme des exécutions enregistrées.
- Deux modèles de concurrence pour un même besoin, des requêtes parallèles bornées vers une source. Le moissonnage par personne emploie des threads et une file bornée (`concurrent_pages`), avec un client synchrone par source. Les recherches par identifiant emploient asyncio (`run_fetch_pool`), avec des fonctions asynchrones par source. Chaque source expose donc deux interfaces HTTP. Chantier à évaluer.
