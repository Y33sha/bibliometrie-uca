"""Tests d'intégration de `DoiPrefixStore` (requêtes contre le schéma réel)."""

from __future__ import annotations

from pipeline.transformation.publishing.doi_prefixes import DoiPrefixStore


def test_breakdown_by_registration_agency_s_execute(sa_sync_conn):
    """La requête (jointure `candidate_dois` × `doi_prefixes`) s'exécute contre le schéma ; sur une base vide, elle renvoie une liste vide."""
    prefix_store = DoiPrefixStore(sa_sync_conn)
    result = prefix_store.breakdown_by_registration_agency()
    assert result == []
