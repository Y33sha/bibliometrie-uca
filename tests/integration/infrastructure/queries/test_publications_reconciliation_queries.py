"""Test d'intégration : validité SQL du comptage des publications (contre le schéma réel)."""

from __future__ import annotations

from pipeline.transformation.publications.publications import count_publications


def test_count_publications_s_execute(sa_sync_conn):
    """Base vide → 0."""
    assert count_publications(sa_sync_conn) == 0
