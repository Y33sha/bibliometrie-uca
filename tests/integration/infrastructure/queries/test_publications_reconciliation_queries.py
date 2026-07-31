"""Test d'intégration : validité SQL du comptage de dédup (contre le schéma réel)."""

from __future__ import annotations

from infrastructure.pipeline.publications.reconciliation import PgPublicationsReconciliationQueries

_Q = PgPublicationsReconciliationQueries()


def test_count_publications_s_execute(sa_sync_conn):
    """`(SP in-périmètre, publications)` via l'EXISTS sur source_authorships ; base vide → (0, 0)."""
    assert _Q.count_publications(sa_sync_conn) == 0
