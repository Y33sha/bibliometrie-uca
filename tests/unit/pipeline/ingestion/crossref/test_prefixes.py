"""Tests du client `api.crossref.org/prefixes` (`parse_member_id`, `fetch_crossref_prefix`).

Les requêtes HTTP passent par la fixture `http_mock`.
"""

from __future__ import annotations

import httpx2
import pytest

from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE
from pipeline.ingestion.crossref.prefixes import fetch_crossref_prefix, parse_member_id

_BASE = "https://api.crossref.org"


def _message(http_mock, path: str, payload) -> None:
    """Déclare la réponse `{"message": payload}` servie pour un chemin de l'API Crossref."""
    http_mock.get(f"{_BASE}{path}").mock(
        return_value=httpx2.Response(200, json={"message": payload})
    )


async def _fetch(prefix: str, sample_doi: str | None = None):
    async with httpx2.AsyncClient() as client:
        return await fetch_crossref_prefix(client, prefix, sample_doi)


# ── parse_member_id ─────────────────────────────────────────────────


def test_parse_member_id_from_url():
    assert parse_member_id("https://id.crossref.org/member/10") == 10
    assert parse_member_id("https://id.crossref.org/member/297") == 297


def test_parse_member_id_from_plain_string():
    """Un enregistrement source renvoie le membre en chaîne numérique, là où un préfixe le renvoie en URL."""
    assert parse_member_id("54812") == 54812


def test_parse_member_id_from_int():
    assert parse_member_id(42) == 42


def test_parse_member_id_none_inputs():
    assert parse_member_id(None) is None
    assert parse_member_id("") is None
    assert parse_member_id("not a url") is None


# ── fetch_crossref_prefix ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_crossref_prefix_ok(http_mock):
    _message(
        http_mock,
        "/prefixes/10.1038",
        {"name": "Nature Publishing Group", "member": "https://id.crossref.org/member/297"},
    )
    assert await _fetch("10.1038") == ("Nature Publishing Group", 297)


@pytest.mark.asyncio
async def test_fetch_crossref_prefix_no_member(http_mock):
    _message(http_mock, "/prefixes/10.1234", {"name": "Foo"})
    assert await _fetch("10.1234") == ("Foo", None)


@pytest.mark.asyncio
async def test_fetch_crossref_prefix_takes_depositing_member_when_registered_one_is_idle(
    http_mock,
):
    """Le préfixe reste enregistré au nom d'un compte sans dépôt : l'enregistrement source donne le compte vivant, dont le nom déclaré l'emporte sur l'imprint de l'enregistrement source."""
    _message(
        http_mock,
        "/prefixes/10.70898",
        {
            "name": "Saint Joseph University of Beirut (independent)",
            "member": "https://id.crossref.org/member/50585",
        },
    )
    _message(
        http_mock,
        "/members/50585",
        {
            "primary-name": "Saint Joseph University of Beirut (independent)",
            "counts": {"total-dois": 0},
        },
    )
    _message(
        http_mock,
        "/works/10.70898/regards.v0i24.486",
        {"publisher": "Regards", "member": "54812"},
    )
    _message(
        http_mock,
        "/members/54812",
        {"primary-name": "Saint Joseph University of Beirut", "counts": {"total-dois": 826}},
    )
    assert await _fetch("10.70898", "10.70898/regards.v0i24.486") == (
        "Saint Joseph University of Beirut",
        54812,
    )


@pytest.mark.asyncio
async def test_fetch_crossref_prefix_keeps_registered_member_when_it_deposits(http_mock):
    _message(http_mock, "/prefixes/10.1007", {"name": "Springer", "member": 297})
    _message(
        http_mock,
        "/members/297",
        {
            "primary-name": "Springer Science and Business Media LLC",
            "counts": {"total-dois": 18946725},
        },
    )
    assert await _fetch("10.1007", "10.1007/abc") == ("Springer", 297)


@pytest.mark.asyncio
async def test_fetch_crossref_prefix_without_sample_doi_asks_nothing_more(http_mock):
    _message(http_mock, "/prefixes/10.1007", {"name": "Springer", "member": 297})
    assert await _fetch("10.1007") == ("Springer", 297)


@pytest.mark.asyncio
async def test_fetch_crossref_prefix_missing_name_is_not_found(http_mock):
    _message(http_mock, "/prefixes/10.1234", {})
    assert await _fetch("10.1234") is NOT_FOUND


@pytest.mark.asyncio
async def test_fetch_crossref_prefix_404_is_not_found(http_mock):
    http_mock.get(f"{_BASE}/prefixes/10.1234").mock(return_value=httpx2.Response(404))
    assert await _fetch("10.1234") is NOT_FOUND


@pytest.mark.asyncio
async def test_fetch_crossref_prefix_network_error_is_unavailable(http_mock):
    http_mock.get(f"{_BASE}/prefixes/10.1234").mock(side_effect=httpx2.ConnectError("boom"))
    assert await _fetch("10.1234") is UNAVAILABLE


@pytest.mark.asyncio
async def test_fetch_crossref_prefix_unavailable_member_check_is_unavailable(http_mock):
    """La vérification du membre échoue : le préfixe entier attend le run suivant, au lieu d'être enregistré au nom du compte peut-être dormant."""
    _message(http_mock, "/prefixes/10.1007", {"name": "Springer", "member": 297})
    http_mock.get(f"{_BASE}/members/297").mock(return_value=httpx2.Response(403))
    assert await _fetch("10.1007", "10.1007/abc") is UNAVAILABLE
