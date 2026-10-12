"""Tests d'intégration de `DoiPrefixesQueries` (requêtes contre le schéma réel)."""

from __future__ import annotations

from pipeline.containers.doi_prefixes import DoiPrefixesQueries


def test_breakdown_by_registration_agency_s_execute(sa_sync_conn):
    """La requête (jointure `candidate_dois` × `doi_prefixes`) est valide contre le
    schéma ; sur une base vide elle renvoie une liste (vide)."""
    repo = DoiPrefixesQueries(sa_sync_conn)
    result = repo.breakdown_by_registration_agency()
    assert result == []
