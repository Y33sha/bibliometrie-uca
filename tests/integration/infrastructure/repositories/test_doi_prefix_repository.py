"""Tests d'intégration de `PgDoiPrefixRepository` (requêtes contre le schéma réel)."""

from __future__ import annotations

from infrastructure.repositories.doi_prefix_repository import PgDoiPrefixRepository


def test_count_dois_by_registration_agency_s_execute(sa_sync_conn):
    """La requête (jointure `candidate_dois` × `doi_prefixes`) est valide contre le
    schéma ; sur une base vide elle renvoie un dict (vide)."""
    repo = PgDoiPrefixRepository(sa_sync_conn)
    result = repo.count_dois_by_registration_agency()
    assert isinstance(result, dict)
