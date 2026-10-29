"""Filtre par catégorie d'accès (`access_clause`).

La clause reçoit la liste des catégories cochées, découpée par le routeur. Plusieurs catégories se combinent par OR ; la catégorie `closed` inclut les publications sans statut open access.
"""

from infrastructure.read_models.filters import (
    OA_CLOSED_STATUSES,
    OA_OPEN_STATUSES,
    access_clause,
)


def test_empty_returns_no_clause():
    assert access_clause([]) is None


def test_single_open_bucket():
    clause = access_clause(["open"])
    assert clause is not None
    assert clause.binds["flt_access_statuses"] == sorted(OA_OPEN_STATUSES)
    assert "IS NULL" not in clause.sql


def test_single_embargo_bucket():
    clause = access_clause(["embargo"])
    assert clause is not None
    assert clause.binds["flt_access_statuses"] == ["embargoed"]


def test_single_closed_bucket_includes_null():
    clause = access_clause(["closed"])
    assert clause is not None
    assert clause.binds["flt_access_statuses"] == sorted(OA_CLOSED_STATUSES)
    assert "p.oa_status IS NULL" in clause.sql


def test_multiple_buckets_combined_with_or():
    clause = access_clause(["closed", "embargo"])
    assert clause is not None
    assert clause.binds["flt_access_statuses"] == sorted({*OA_CLOSED_STATUSES, "embargoed"})
    assert " OR " in clause.sql
    assert "p.oa_status IS NULL" in clause.sql


def test_unknown_bucket_is_ignored():
    assert access_clause(["bogus"]) is None
    # Une catégorie inconnue, cochée avec une catégorie valide, est ignorée.
    clause = access_clause(["open", "bogus"])
    assert clause is not None
    assert clause.binds["flt_access_statuses"] == sorted(OA_OPEN_STATUSES)
