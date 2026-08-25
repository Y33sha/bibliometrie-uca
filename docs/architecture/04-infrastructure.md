# Infrastructure — adapters sortants

*À jour le 2026-06-30.*

Contenu :

- **`db/`** — bas niveau DB (engine, schéma, MetaData) :
  - `schema.sql` (snapshot descriptif, régénéré par `python -m interfaces.cli.dev.dump_schema`), `seed.sql`
  - `tables.py` — MetaData SQLAlchemy explicite (source pour `alembic revision --autogenerate`). Les migrations vivent dans `alembic/versions/` à la racine, appliquées via `alembic upgrade head`.
  - `engine.py` — Engine SQLAlchemy synchrone (driver `postgresql+psycopg`). Source unique pour l'API FastAPI (via le threadpool Starlette) et le pipeline.
- **`read_models/`** — read side du CQRS : projections de lecture pour l'API et le frontend, implémentant `application/ports/read_models/*`. Un fichier par agrégat, les modules volumineux éclatés en sous-dossier (`persons/`, `publications/`, `stats/` avec `list.py`/`facets.py`/`detail.py`/…) ; le helper neutre `filters.py` (clauses de périmètre partagées) reste à la racine. Lecture seule, orientée **UI** : projections plates, jointures, agrégations, filtres dynamiques (facets) ; retour de records (`dict[str, object]` ou `Row[Any]`) directement consommables par les routers et leur Pydantic, pas d'hydratation d'agrégat.
- **`pipeline/`** — gateways SQL des phases du pipeline, implémentant `application/ports/pipeline/*` : un module par phase, regroupés par contexte (`extract/`, `normalize/`, `affiliations/`, `authorships/`, `persons/`, `publications/`) ou à la racine (`countries.py`, `metadata_correction.py`, `oa_status.py`, `relations.py`, `subjects.py`, `perimeter.py`). Lecture **et** écriture ensemblistes — une phase d'ETL lit ses entrées et matérialise ses sorties (marquage d'état, vidange de `staging`, consolidation), sans hydratation d'agrégat. `change_detection.py` porte le hash de détection de changement partagé par l'extraction et la normalisation.
- **`repositories/`** — adapters PostgreSQL implémentant les ports `application/ports/repositories/*` : `person_repository/`, `publication_repository.py`, `journal_repository.py`, `structure_repository.py`, `authorship_repository.py`, `address_repository.py`, `publisher_repository.py`, `perimeter_repository.py`, `config_repository.py`, `audit_repository.py`. Factories exposées dans `__init__.py` (`person_repository(conn)`, `publication_repository(conn)`, …). Orienté **écriture + invariants** : hydrate des agrégats riches (`Publication`, `Person`, …) avec leurs VOs et règles métier, garantit la cohérence à l'écriture. Signatures en termes métier (`find_by_doi`, `merge_into`, `save`).
- **`jsonb_models/`** — modèles Pydantic des colonnes JSONB (`publications.external_ids`, `structures.api_ids`, …). Validation + normalisation à l'écriture, parsing typé à la lecture. Pas de dépendance SQLAlchemy : c'est de la modélisation de données, juste rangée côté infra parce que la forme est dictée par le schéma DB.
- **`sources/`** — adapters HTTP/SQL des sources externes (HAL, OpenAlex, WoS, ScanR, theses.fr, Crossref, DataCite). Pour les sources moissonnées (HAL, OpenAlex, WoS, ScanR, theses.fr), chaque source expose un `Pg<Source>ExtractAdapter` qui implémente le port `application.ports.pipeline.extract.<source>.<Source>ExtractAdapter` ; l'orchestrateur (qui hérite du `SourceExtractor` de `application/pipeline/extract/base.py`) vit côté application. Crossref et DataCite sont interrogées par DOI (`fetch_missing_doi`), sans moissonnage.
- **`observability/`** — logging JSON structuré (`log.py`), historique d'exécution des phases du pipeline (`phase_executions.py`), découpage du log par phase (`phase_logs.py`).
- **Divers** à la racine : `settings.py` (pydantic-settings), `pipeline_lock.py` (verrou d'exécution concurrente du pipeline).

## Discipline transactionnelle

Le projet suit la règle Cosmic Python : **les repositories ne commitent jamais**. Le commit est la prérogative du use case (qui sait si une unité de travail est terminée), pas de l'adapter de persistance (qui ne sait jamais où il se situe dans une transaction plus large).

### Règles

1. **Zéro `commit()` dans `infrastructure/repositories/`.** Vérifiable par `grep -rn "\.commit()" infrastructure/repositories/` — doit retourner zéro résultat. Les méthodes du repo modifient la transaction courante ; c'est le caller qui décide quand persister.

2. **Les use-cases pipeline commitent.** Chaque orchestrateur dans `application/pipeline/*` est responsable de son unité de travail : `commit()` en sortie nominale, `rollback()` dans `except Exception` (crash : état inconnu). Le cas `except KeyboardInterrupt` commite plutôt que rollbacker : un Ctrl+C utilisateur est un signal de « arrête-toi proprement », pas un crash.

3. **Savepoints pour les sous-unités résilientes.** Quand une boucle doit isoler les échecs item-par-item sans rollbacker tout le batch, utiliser `application/pipeline/_savepoint.py` (wrapper sur `connection.begin_nested()` de SQLAlchemy). Exemple : `normalize/base.py` avec `USE_SAVEPOINT=True`.

### Exceptions assumées

- **Batch commits dans les pipelines** (par exemple `normalize/base.py`, `affiliations/resolve_addresses.py`, `extract/refetch_truncated.py`) : commit toutes les N opérations pour qu'un crash sur un batch de 100k+ items ne perde pas tout. Suppose des phases idempotentes (vrai par construction).

- **Commits dans `infrastructure/sources/*`** : extracteurs API qui commitent page-par-page. Adapters batch, pas repositories — les appels HTTP sont coûteux, les pages déjà fetchées doivent survivre.
