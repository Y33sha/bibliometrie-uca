"""Tests unitaires de `build_params` (adapter OpenAlex)."""

from __future__ import annotations

import pytest

from infrastructure.sources.openalex import init_auth
from infrastructure.sources.openalex.extract_openalex import build_params


@pytest.fixture(autouse=True)
def _reset_auth():
    """Réinitialise l'état d'auth global avant chaque test pour déterminer
    les `auth_params()` ajoutés par `build_params`."""
    init_auth(api_key=None, email="")
    yield
    init_auth(api_key=None, email="")


class TestBuildParams:
    def test_year_filter(self):
        params = build_params(["I1"], year=2024)
        assert params["filter"] == ("authorships.institutions.lineage:I1,publication_year:2024")

    def test_since_overrides_year(self):
        # Quand `since` est fourni, le filter passe sur `from_updated_date`
        # et `year` est ignoré.
        params = build_params(["I1"], year=2024, since="2026-05-01")
        assert params["filter"] == (
            "authorships.institutions.lineage:I1,from_updated_date:2026-05-01"
        )

    def test_lineage_joins_multiple_institutions(self):
        # Plusieurs institutions OR (pipe) côté lineage.
        params = build_params(["I1", "I2", "I3"], year=2024)
        assert params["filter"] == (
            "authorships.institutions.lineage:I1|I2|I3,publication_year:2024"
        )

    def test_lineage_empty_when_no_institutions(self):
        # Cas dégénéré : pas d'institutions → lineage vide. La requête sera
        # toujours envoyée mais ne ramènera rien. À pinner pour ne pas régresser
        # silencieusement.
        params = build_params([], year=2024)
        assert params["filter"] == "authorships.institutions.lineage:,publication_year:2024"

    def test_select_and_cursor_present(self):
        params = build_params(["I1"], year=2024)
        assert "select" in params and params["select"]
        assert params["cursor"] == "*"

    def test_custom_cursor(self):
        params = build_params(["I1"], year=2024, cursor="abc123")
        assert params["cursor"] == "abc123"

    def test_auth_api_key_included(self):
        init_auth(api_key="testkey")
        params = build_params(["I1"], year=2024)
        assert params.get("api_key") == "testkey"
        assert "mailto" not in params

    def test_auth_email_fallback(self):
        # Sans api_key, l'email fait basculer sur le polite pool via `mailto`.
        init_auth(email="test@example.com")
        params = build_params(["I1"], year=2024)
        assert params.get("mailto") == "test@example.com"
        assert "api_key" not in params
