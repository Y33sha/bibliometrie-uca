"""Tests d'intégration des requêtes d'enrichissement (validité contre le schéma réel)."""

from __future__ import annotations

from infrastructure.queries.pipeline.enrich import (
    count_publications_by_oa_status,
    count_stale_publications,
)


def test_count_stale_publications_s_execute(sa_sync_conn):
    """Le prédicat de staleness OA est valide contre le schéma ; base vide → 0."""
    assert count_stale_publications(sa_sync_conn, staleness_days=30) == 0


def test_count_publications_by_oa_status_s_execute(sa_sync_conn):
    """L'agrégation par statut OA est valide ; base vide → dict (vide)."""
    assert count_publications_by_oa_status(sa_sync_conn) == {}
