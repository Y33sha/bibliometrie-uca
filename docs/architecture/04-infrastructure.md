# `infrastructure/` — adapters sortants

Contenu :

- **`db/`** — bas niveau DB (engine, schéma, MetaData) :
  - `schema.sql` (snapshot descriptif, régénéré par `python -m infrastructure.db.dump_schema`), `seed.sql`
  - `tables.py` — MetaData SQLAlchemy explicite (source pour `alembic revision --autogenerate`). Les migrations vivent dans `alembic/versions/` à la racine, appliquées via `alembic upgrade head`.
  - `engine.py` — Engine SQLAlchemy synchrone (driver `postgresql+psycopg`). Source unique pour l'API FastAPI (via le threadpool Starlette) et le pipeline.
- **`queries/`** — query services SQL : projections plates pour lectures (listings, facets, détails, stats). Implémentent les ports `application/ports/api/*` et `application/ports/pipeline/*`. Un fichier par agrégat ou phase pipeline ; les modules volumineux sont éclatés en sous-dossier (`queries/persons/`, `queries/publications/` pour `list.py`, `facets.py`, `detail.py`, …).
- **`repositories/`** — adapters PostgreSQL implémentant les ports `application/ports/repositories/*` : `person_repository/`, `publication_repository.py`, `journal_repository.py`, `structure_repository.py`, `authorship_repository.py`, `address_repository.py`, `publisher_repository.py`, `perimeter_repository.py`, `audit_repository.py`. Factories exposées dans `__init__.py` (`person_repository(conn)`, `publication_repository(conn)`, …).
- **`jsonb_models/`** — modèles Pydantic des colonnes JSONB (`publications.external_ids`, `structures.api_ids`, …). Validation + normalisation à l'écriture, parsing typé à la lecture. Pas de dépendance SQLAlchemy : c'est de la modélisation de données, juste rangée côté infra parce que la forme est dictée par le schéma DB.
- **`sources/`** — adapters HTTP/SQL des sources externes (HAL, OpenAlex, WoS, ScanR, theses.fr, Crossref). Pour la phase extract, chaque source expose un `Pg<Source>ExtractAdapter` qui implémente le port `application.ports.pipeline.extract.<source>.<Source>ExtractAdapter` ; l'orchestrateur (qui hérite du `SourceExtractor` de `application/pipeline/extract/base.py`) vit côté application. Inclut aussi `zenodo/` (adapter HTTP de résolution concept DOI → version DOI, utilisé pendant la normalisation HAL et OpenAlex).
- **Divers** : `log.py` (JSON structuré), `settings.py` (pydantic-settings), `perimeter.py`, `addresses.py`, `api_retry.py`, `api_limits.py`, `pipeline_metrics.py`, `pipeline_status.py`, `app_config.py`, `db/dump_schema.py`.

## Pourquoi `queries/` ET `repositories/` au lieu d'une seule abstraction SQL ?

C'est un compromis CQRS-light :

- `repositories/` est orienté **écriture + invariants** : hydrate des agrégats riches (`Publication`, `Person`, …) avec leurs VOs et règles métier, garantit la cohérence à l'écriture. Signatures en termes métier (`find_by_doi`, `merge_into`, `save`).
- `queries/` est orienté **lecture pour l'UI** : projections plates, jointures, agrégations, filtres dynamiques (facets). Retourne des records (`dict[str, object]` ou `Row[Any]`) directement consommables par les routers et leur Pydantic ; pas d'hydratation d'agrégat.

Hydrater une `Publication` complète pour afficher une ligne dans une liste de 50 publis serait du gaspillage. Inversement, faire passer une écriture d'agrégat par une projection SQL ad-hoc fragiliserait les invariants. Les deux abstractions cohabitent donc volontairement.

`infrastructure/` n'importe que les ports (`application/ports/*`) et le domaine — jamais les use-cases applicatifs (`application/*.py` hors `ports/`).

## Discipline transactionnelle

Le projet suit la règle Cosmic Python : **les repositories ne commitent jamais**. Le commit est la prérogative du use case (qui sait si une unité de travail est terminée), pas de l'adapter de persistance (qui ne sait jamais où il se situe dans une transaction plus large).

### Règles

1. **Zéro `commit()` dans `infrastructure/repositories/`.** Vérifiable par `grep -rn "\.commit()" infrastructure/repositories/` — doit retourner zéro résultat. Les méthodes du repo modifient la transaction courante ; c'est le caller qui décide quand persister.

2. **Les use-cases pipeline commitent.** Chaque orchestrateur dans `application/pipeline/*` est responsable de son unité de travail : `commit()` en sortie nominale, `rollback()` dans `except Exception` (crash : état inconnu). Le cas `except KeyboardInterrupt` commite plutôt que rollbacker : un Ctrl+C utilisateur est un signal de « arrête-toi proprement », pas un crash.

3. **Savepoints pour les sous-unités résilientes.** Quand une boucle doit isoler les échecs item-par-item sans rollbacker tout le batch, utiliser `application/pipeline/_savepoint.py` (wrapper sur `connection.begin_nested()` de SQLAlchemy). Exemple : `normalize/base.py` avec `USE_SAVEPOINT=True`.

### Exceptions assumées

- **Batch commits dans les pipelines** (`create_publications.py`, `enrich_journal_apc.py`, `normalize/base.py`, `resolve_addresses.py`, `refetch_truncated.py`) : commit toutes les N opérations pour qu'un crash sur un batch de 100k+ items ne perde pas tout. Suppose des phases idempotentes (vrai par construction).

- **Commits dans `infrastructure/sources/*`** : extracteurs API qui commitent page-par-page. Adapters batch, pas repositories — les appels HTTP sont coûteux, les pages déjà fetchées doivent survivre.
