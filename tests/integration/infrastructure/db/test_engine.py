"""Réglages de session des connexions ouvertes par l'engine du projet."""

import pytest
from sqlalchemy import text

from infrastructure.db.engine import build_sync_engine
from infrastructure.settings import settings
from tests.integration.helpers.db import DB_NAME


def test_connections_force_custom_plans(monkeypatch: pytest.MonkeyPatch):
    """Une requête répétée garde un plan calculé selon ses paramètres : le plan générique de PostgreSQL ralentit fortement les requêtes des rapports à partir de leur 11ᵉ exécution."""
    monkeypatch.setattr(settings, "db_name", DB_NAME)
    engine = build_sync_engine()
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SHOW plan_cache_mode")).scalar_one() == "force_custom_plan"
    finally:
        engine.dispose()
