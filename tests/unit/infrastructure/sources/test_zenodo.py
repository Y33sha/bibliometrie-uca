"""Tests de l'adapter HTTP Zenodo (`resolve_zenodo_concept_doi`).

Vérifie l'extraction du champ `conceptdoi`, les cas dégénérés (DOI non Zenodo,
record sans concept, 404) et la remontée d'erreur temporaire (statut 5xx).
`requests.get` est monkeypatché : aucun appel réseau.
"""

from __future__ import annotations

import pytest

from domain.sources.zenodo import ZenodoResolutionError
from infrastructure.sources import zenodo


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(zenodo.time, "sleep", lambda _s: None)


def _patch_get(monkeypatch, resp: _Resp) -> None:
    monkeypatch.setattr(zenodo.requests, "get", lambda url, **kw: resp)


def test_returns_concept_doi(monkeypatch):
    _patch_get(monkeypatch, _Resp(200, {"conceptdoi": "10.5281/zenodo.100"}))
    result = zenodo.resolve_zenodo_concept_doi("10.5281/zenodo.101", api_base="https://x/api")
    assert result == "10.5281/zenodo.100"


def test_no_concept_field_returns_none(monkeypatch):
    """Dépôt non versionné : pas de `conceptdoi` → None (l'orchestrateur posera le DOI propre)."""
    _patch_get(monkeypatch, _Resp(200, {"doi": "10.5281/zenodo.101"}))
    assert zenodo.resolve_zenodo_concept_doi("10.5281/zenodo.101", api_base="https://x/api") is None


def test_non_zenodo_doi_returns_none_without_http(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("ne doit pas appeler l'API")

    monkeypatch.setattr(zenodo.requests, "get", _boom)
    assert zenodo.resolve_zenodo_concept_doi("10.1234/not-zenodo", api_base="https://x/api") is None


def test_404_returns_none(monkeypatch):
    _patch_get(monkeypatch, _Resp(404))
    assert zenodo.resolve_zenodo_concept_doi("10.5281/zenodo.999", api_base="https://x/api") is None


def test_server_error_raises_temporary(monkeypatch):
    _patch_get(monkeypatch, _Resp(503))
    with pytest.raises(ZenodoResolutionError):
        zenodo.resolve_zenodo_concept_doi("10.5281/zenodo.1", api_base="https://x/api")
