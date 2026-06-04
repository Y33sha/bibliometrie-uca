# Application — services et orchestrateurs

Contenu :

- **Services métier** : `persons.py`, `publications.py`, `journals.py`, `authorships/core.py`, `authorships/assign_orphans.py`, `structures.py`, `addresses_countries.py`, `addresses_structures.py`, `audit.py`, `config.py`, `publishers.py`. Ces services reçoivent leurs dépendances par injection (kwarg `repo=`, `audit_repo=`, `queries=`).
- **Orchestrateurs pipeline** dans `application/pipeline/` :
  - `extract/` — tous les pilotes d'ingestion → staging :
    - `extract_<source>.py` — extraction de masse par source (HAL, OpenAlex, WoS, ScanR, theses.fr) ; pilote la pagination
    - `fetch_missing_doi.py` — fetch cross-source par DOI
    - `fetch_missing_hal_id.py` — fetch HAL par halId / NNT depuis les références d'autres sources
    - `refetch_truncated.py` — re-fetch OpenAlex des works tronqués à 100 auteurs

    Chaque pilote délègue HTTP + SQL à un adapter via un Port (`application/ports/pipeline/extract/<nom>.py`).
  - `normalize/` — staging → tables sources (un module par source)
  - `affiliations/` — propagation adresses ↔ structures vers `source_authorships.in_perimeter` et la table de jointure `source_authorship_structures`
  - `publications/` — création/merge publications canoniques
  - `persons/` — création personnes + formes de noms
  - `authorships/` — reconstruction de la table de vérité
  - `countries/` — recalcul pays publications
  - `subjects/` — ingestion sujets/mots-clés
  - `cooccurrences/` — recalcul co-occurrences sujets
  - `enrich/` — Unpaywall, APC
- **Ports** (`application/ports/*`) : interfaces Protocol pour les query services (adapters dans `infrastructure/queries/*`) et pour les repositories d'agrégats (`application/ports/repositories/*`, implémentés dans `infrastructure/repositories/*`).

Interdiction : **`application/` ne peut pas importer `infrastructure/`**. Toute nouvelle dépendance doit passer par un port. Vérifié par le contrat `layered` d'`import-linter`.

## Patterns d'injection

### Services applicatifs ↔ repositories

Les services acceptent leur repo (et autres dépendances : audit_repo, queries, …) en kwarg keyword-only :

```python
def set_rejected(
    person_id: int,
    rejected: bool,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    repo.set_rejected(person_id, rejected)
    emit_event(audit_repo, "person.rejected", ...)
```

Les callers directs (routers, tests, scripts CLI) créent l'instance via la factory :

```python
from infrastructure.repositories import person_repository
set_rejected(person_id, True, repo=person_repository(conn))
```

### Orchestrateurs pipeline ↔ query services + repositories

Les orchestrateurs dans `application/pipeline/*` ne peuvent pas importer `infrastructure.*` directement. Deux mécanismes :

1. **Query services** (SQL de la phase) : passés en paramètre typés par un port `application/ports/*`. L'entry point (`run_pipeline.py` ou `interfaces/cli/pipeline/*`) instancie les adapters `Pg*Queries` concrets.

2. **Repositories** (ex. `PublicationRepository`) : quand un orchestrateur a besoin d'un repo, on passe un **factory callable** `repo_factory: Callable[[Connection], XRepository]` au constructeur. L'orchestrateur appelle `self._repo = self._repo_factory(conn)` dans `preload_caches()` ou au début de `run()`.

Exemple depuis `run_pipeline.py` :

```python
from infrastructure.queries.pipeline.persons_create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository

PgPersonsCreateQueries()        # adapter query service
person_repository(conn)         # factory repository
```

### Batch commits dans le pipeline

La règle générale est que les use-cases commitent (cf. [discipline transactionnelle](04-infrastructure.md#discipline-transactionnelle)). Côté pipeline, les phases qui traitent des dizaines de milliers d'items commitent **par batch** (toutes les N opérations) pour qu'un crash ne perde pas tout le travail déjà fait. Concerné : `create_publications.py`, `enrich_journal_apc.py`, `normalize/base.py`, `resolve_addresses.py`, `refetch_truncated.py`. Suppose des phases idempotentes (vrai par construction).
