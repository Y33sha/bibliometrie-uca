"""Détecteur central de présence des credentials par source d'API tierce.

`source_credentials_missing` est la seule source de vérité consultée par toutes
les phases (extraction, cross-import, refresh stale, enrichissements). HAL et
theses.fr sont des API publiques ; OpenAlex accepte clé API ou email ; WoS exige
sa clé ; ScanR ses credentials ; Crossref/DataCite/Unpaywall l'email polite pool.
"""

from unittest.mock import patch

import pytest

from infrastructure.sources import config


def _detect(source: str) -> str | None:
    # `conn` inutilisé : les getters sont patchés ; None suffit.
    return config.source_credentials_missing(None, source)


@pytest.mark.parametrize("source", ["hal", "theses"])
def test_public_apis_never_missing(source):
    assert _detect(source) is None


@pytest.mark.parametrize(
    ("api_key", "email", "expected_ok"),
    [("k", None, True), (None, "e@x", True), ("k", "e@x", True), (None, None, False)],
)
def test_openalex_accepts_key_or_email(api_key, email, expected_ok):
    with (
        patch.object(config, "get_openalex_api_key", return_value=api_key),
        patch.object(config, "get_polite_pool_email_optional", return_value=email),
    ):
        assert (_detect("openalex") is None) is expected_ok


@pytest.mark.parametrize(("api_key", "expected_ok"), [("k", True), ("", False)])
def test_wos_requires_api_key(api_key, expected_ok):
    with patch.object(config, "get_wos_api_key", return_value=api_key):
        assert (_detect("wos") is None) is expected_ok


@pytest.mark.parametrize(("creds", "expected_ok"), [(("u", "p"), True), (("", ""), False)])
def test_scanr_requires_credentials(creds, expected_ok):
    with patch.object(config, "get_scanr_credentials", return_value=creds):
        assert (_detect("scanr") is None) is expected_ok


@pytest.mark.parametrize("source", ["crossref", "datacite", "unpaywall"])
@pytest.mark.parametrize(("email", "expected_ok"), [("e@x", True), (None, False)])
def test_email_driven_sources_require_polite_email(source, email, expected_ok):
    with patch.object(config, "get_polite_pool_email_optional", return_value=email):
        assert (_detect(source) is None) is expected_ok
