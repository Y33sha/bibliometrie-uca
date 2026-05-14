"""Constantes communes côté base de données.

Réduit à `SANDBOX_DB_NAME` depuis le passage à SA Core : les
connexions effectives passent par `infrastructure/db/engine.py`
(`get_sync_engine().connect()`).
"""

SANDBOX_DB_NAME = "bibliometrie_sandbox"
