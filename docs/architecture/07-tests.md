# Tests

- **Unit** (`tests/unit/`) — pas de DB. Couvre `domain/`, `application/` (services avec mocks), parsing des normalizers et des adapters sources (`infrastructure/sources/<source>/parsing.py`), infrastructure pure (log, pipeline_metrics).
- **Intégration** (`tests/integration/`) — base `bibliometrie_test` créée à la volée (`alembic upgrade head` sur DB vierge), fixtures `db` (curseur psycopg avec rollback) et `sa_sync_conn` (Connection SA avec rollback). Couvre les routers, les orchestrateurs pipeline, et les adapters repositories.

Conftest splitté :

- `tests/conftest.py` — cross-cutting (mock `setup_logger` pour éviter la pollution disque, caches)
- `tests/integration/conftest.py` — setup BDD via Alembic, fixtures `db` / `sa_sync_conn`

Seuil de couverture `fail_under = 85` (`[tool.coverage.report]` dans `pyproject.toml`). Mesure courante : 86 %.

Les modules de wiring HTTP des adapters sources sont exclus du calcul ; leur logique pure vit dans `<source>/parsing.py` et est couverte par tests unitaires.
