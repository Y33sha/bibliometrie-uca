"""Test d'intégration : validité SQL du comptage de dédup (contre le schéma réel)."""

from __future__ import annotations

from infrastructure.queries.pipeline.publications.reconciliation import count_publications


def test_count_publications_s_execute(sa_sync_conn):
    """`(SP in-périmètre, publications)` via l'EXISTS sur source_authorships ; base vide → (0, 0)."""
    assert count_publications(sa_sync_conn) == 0
