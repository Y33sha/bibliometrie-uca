"""Identifiants d'accès aux API des sources, lus dans l'environnement.

Leur absence se traduit selon la source : une valeur vide ou un couple vide. `source_credentials_missing` en déduit le motif d'absence. HAL et theses.fr sont des API publiques. OpenAlex accepte une clé d'API ou l'adresse polite pool. WoS exige sa clé, ScanR ses identifiants, Crossref, DataCite et Unpaywall l'adresse polite pool.
"""

from unittest.mock import patch

import pytest
from pydantic import SecretStr

from infrastructure.settings import settings
from pipeline.ingestion import credentials
from pipeline.ingestion.credentials import (
    get_openalex_api_key,
    get_scanr_credentials,
    get_wos_api_key,
)


def _detect(source: str) -> str | None:
    return credentials.source_credentials_missing(source)


class TestSecretsDAcces:
    def test_cle_openalex_absente(self, monkeypatch):
        monkeypatch.setattr(settings, "openalex_api_key", SecretStr(""))
        assert get_openalex_api_key() is None

    def test_cle_openalex_presente(self, monkeypatch):
        monkeypatch.setattr(settings, "openalex_api_key", SecretStr("clé"))
        assert get_openalex_api_key() == "clé"

    def test_cle_wos(self, monkeypatch):
        monkeypatch.setattr(settings, "wos_api_key", SecretStr("clé-wos"))
        assert get_wos_api_key() == "clé-wos"

    def test_identifiants_scanr_complets(self, monkeypatch):
        monkeypatch.setattr(settings, "scanr_username", "utilisateur")
        monkeypatch.setattr(settings, "scanr_password", SecretStr("secret"))
        assert get_scanr_credentials() == ("utilisateur", "secret")

    @pytest.mark.parametrize(
        ("utilisateur", "secret"), [("utilisateur", ""), ("", "secret"), ("", "")]
    )
    def test_identifiants_scanr_incomplets(self, monkeypatch, utilisateur, secret):
        """Un couple d'identifiants incomplet est tenu pour absent."""
        monkeypatch.setattr(settings, "scanr_username", utilisateur)
        monkeypatch.setattr(settings, "scanr_password", SecretStr(secret))
        assert get_scanr_credentials() == ("", "")


@pytest.mark.parametrize("source", ["hal", "theses"])
def test_public_apis_never_missing(source):
    assert _detect(source) is None


@pytest.mark.parametrize("source", ["doi.org", "doaj"])
def test_sources_sans_credential_connu(source):
    """Une API publique absente de la liste de la fonction ne réclame aucun identifiant."""
    assert _detect(source) is None


@pytest.mark.parametrize(
    ("api_key", "email", "expected_ok"),
    [("k", None, True), (None, "e@x", True), ("k", "e@x", True), (None, None, False)],
)
def test_openalex_accepts_key_or_email(api_key, email, expected_ok):
    with (
        patch.object(credentials, "get_openalex_api_key", return_value=api_key),
        patch.object(credentials, "get_polite_pool_email_optional", return_value=email),
    ):
        assert (_detect("openalex") is None) is expected_ok


@pytest.mark.parametrize(("api_key", "expected_ok"), [("k", True), ("", False)])
def test_wos_requires_api_key(api_key, expected_ok):
    with patch.object(credentials, "get_wos_api_key", return_value=api_key):
        assert (_detect("wos") is None) is expected_ok


@pytest.mark.parametrize(("creds", "expected_ok"), [(("u", "p"), True), (("", ""), False)])
def test_scanr_requires_credentials(creds, expected_ok):
    with patch.object(credentials, "get_scanr_credentials", return_value=creds):
        assert (_detect("scanr") is None) is expected_ok


@pytest.mark.parametrize("source", ["crossref", "datacite", "unpaywall"])
@pytest.mark.parametrize(("email", "expected_ok"), [("e@x", True), (None, False)])
def test_email_driven_sources_require_polite_email(source, email, expected_ok):
    with patch.object(credentials, "get_polite_pool_email_optional", return_value=email):
        assert (_detect(source) is None) is expected_ok
