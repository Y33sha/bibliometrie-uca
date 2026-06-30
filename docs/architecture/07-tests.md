# Tests

*À jour le 2026-06-30.*

- **Unit** (`tests/unit/`) — pas de DB. Couvre `domain/`, `application/` (services avec mocks), le parsing des normalizers et des adapters sources (logique pure rangée selon la source : `parsing.py`, `fields.py`, ou le module d'extraction), l'infrastructure pure (log, métriques).
- **Intégration** (`tests/integration/`) — base `bibliometrie_test` créée à la volée (`alembic upgrade head` sur DB vierge), fixtures `db` (curseur psycopg avec rollback) et `sa_sync_conn` (Connection SA avec rollback). Couvre les routers, les orchestrateurs pipeline, et les adapters repositories.

Conftest splitté :

- `tests/conftest.py` — cross-cutting (mock `setup_logger` pour éviter la pollution disque, caches)
- `tests/integration/conftest.py` — setup BDD via Alembic, fixtures `db` / `sa_sync_conn`

Seuil de couverture `fail_under = 85` (`[tool.coverage.report]` dans `pyproject.toml`).

Les modules de wiring HTTP des adapters sources sont exclus du calcul ; leur logique pure (parsing des payloads) est isolée dans des modules dédiés par source et couverte par tests unitaires.
