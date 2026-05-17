"""Tests unitaires de `infrastructure/sources/openalex/parsing.py`."""

from __future__ import annotations

import pytest

from infrastructure.sources.openalex import init_auth
from infrastructure.sources.openalex.parsing import (
    build_params,
    compute_meta_hash,
    extract_doi,
    extract_openalex_id,
)


@pytest.fixture(autouse=True)
def _reset_auth():
    """Réinitialise l'état d'auth global avant chaque test pour déterminer
    les `auth_params()` ajoutés par `build_params`."""
    init_auth(api_key=None, email="")
    yield
    init_auth(api_key=None, email="")


class TestExtractOpenalexId:
    def test_strips_url_prefix(self):
        assert extract_openalex_id({"id": "https://openalex.org/W2741809807"}) == "W2741809807"

    def test_no_prefix_unchanged(self):
        # `str.replace` ne fait rien si la sous-chaîne est absente — pas
        # d'erreur, on retombe sur l'id tel quel.
        assert extract_openalex_id({"id": "W2741809807"}) == "W2741809807"


class TestExtractDoi:
    def test_strips_url_prefix(self):
        assert extract_doi({"doi": "https://doi.org/10.1000/abc"}) == "10.1000/abc"

    def test_bare_doi(self):
        assert extract_doi({"doi": "10.1000/abc"}) == "10.1000/abc"

    def test_none_when_absent(self):
        assert extract_doi({}) is None

    def test_none_when_explicit_none(self):
        assert extract_doi({"doi": None}) is None


class TestComputeMetaHash:
    def test_identical_metadata_same_hash(self):
        a = {"title": "Foo", "publication_year": 2024, "authorships": [{"a": 1}]}
        b = {"title": "Foo", "publication_year": 2024, "authorships": [{"a": 1}]}
        assert compute_meta_hash(a) == compute_meta_hash(b)

    def test_authorships_difference_ignored(self):
        # `compute_meta_hash` filtre les authorships : deux raw_data qui
        # diffèrent uniquement sur ce champ produisent le même hash.
        # Justifie le mécanisme `meta_hash` vs `raw_hash` pour l'idempotence
        # après refetch tronqué.
        a = {"title": "Foo", "authorships": [{"a": 1}]}
        b = {"title": "Foo", "authorships": [{"a": 1}, {"b": 2}]}
        assert compute_meta_hash(a) == compute_meta_hash(b)

    def test_metadata_change_changes_hash(self):
        a = {"title": "Foo", "authorships": [{"a": 1}]}
        b = {"title": "Bar", "authorships": [{"a": 1}]}
        assert compute_meta_hash(a) != compute_meta_hash(b)


class TestBuildParams:
    def test_year_filter(self):
        params = build_params(year=2024, institution_ids=["I1"])
        assert params["filter"] == ("authorships.institutions.lineage:I1,publication_year:2024")

    def test_since_overrides_year(self):
        # Quand `since` est fourni, le filter passe sur `from_updated_date`
        # et `year` est ignoré.
        params = build_params(year=2024, institution_ids=["I1"], since="2026-05-01")
        assert params["filter"] == (
            "authorships.institutions.lineage:I1,from_updated_date:2026-05-01"
        )

    def test_lineage_joins_multiple_institutions(self):
        # Plusieurs institutions OR (pipe) côté lineage.
        params = build_params(year=2024, institution_ids=["I1", "I2", "I3"])
        assert params["filter"] == (
            "authorships.institutions.lineage:I1|I2|I3,publication_year:2024"
        )

    def test_lineage_empty_when_no_institutions(self):
        # Cas dégénéré : pas d'institutions → lineage vide. La requête sera
        # toujours envoyée mais ne ramènera rien. À pinner pour ne pas régresser
        # silencieusement.
        params = build_params(year=2024, institution_ids=None)
        assert params["filter"] == "authorships.institutions.lineage:,publication_year:2024"

    def test_select_and_cursor_present(self):
        params = build_params(year=2024, institution_ids=["I1"])
        assert "select" in params and params["select"]
        assert params["cursor"] == "*"

    def test_custom_cursor(self):
        params = build_params(year=2024, institution_ids=["I1"], cursor="abc123")
        assert params["cursor"] == "abc123"

    def test_auth_api_key_included(self):
        init_auth(api_key="testkey")
        params = build_params(year=2024, institution_ids=["I1"])
        assert params.get("api_key") == "testkey"
        assert "mailto" not in params

    def test_auth_email_fallback(self):
        # Sans api_key, l'email fait basculer sur le polite pool via `mailto`.
        init_auth(email="test@example.com")
        params = build_params(year=2024, institution_ids=["I1"])
        assert params.get("mailto") == "test@example.com"
        assert "api_key" not in params
