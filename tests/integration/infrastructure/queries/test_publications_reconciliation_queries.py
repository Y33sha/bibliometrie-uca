"""Test d'intégration : validité SQL du comptage de dédup (contre le schéma réel)."""

from __future__ import annotations

from infrastructure.queries.pipeline.publications_reconciliation import count_dedup_inputs


def test_count_dedup_inputs_s_execute(sa_sync_conn):
    """`(SP in-périmètre, publications)` via l'EXISTS sur source_authorships ; base vide → (0, 0)."""
    assert count_dedup_inputs(sa_sync_conn) == (0, 0)
