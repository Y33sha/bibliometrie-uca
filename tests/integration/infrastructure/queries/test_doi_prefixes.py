"""Tests d'intégration de `PgDoiPrefixesQueries` (requêtes contre le schéma réel)."""

from __future__ import annotations

from infrastructure.pipeline.doi_prefixes import PgDoiPrefixesQueries


def test_breakdown_by_registration_agency_s_execute(sa_sync_conn):
    """La requête (jointure `candidate_dois` × `doi_prefixes`) est valide contre le
    schéma ; sur une base vide elle renvoie une liste (vide)."""
    repo = PgDoiPrefixesQueries(sa_sync_conn)
    result = repo.breakdown_by_registration_agency()
    assert result == []
