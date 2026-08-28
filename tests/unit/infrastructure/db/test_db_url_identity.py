"""Choix de l'identité de connexion : l'API se connecte au rôle restreint, le reste au propriétaire du schéma."""

import pytest
from pydantic import SecretStr

from infrastructure.db.engine import db_url
from infrastructure.settings import settings


@pytest.fixture
def _identities(monkeypatch):
    monkeypatch.setattr(settings, "db_owner_user", "proprietaire")
    monkeypatch.setattr(settings, "db_owner_password", SecretStr("secret-proprietaire"))
    monkeypatch.setattr(settings, "db_app_user", "applicatif")
    monkeypatch.setattr(settings, "db_app_password", SecretStr("secret-applicatif"))


class TestConnectionIdentity:
    def test_api_uses_the_restricted_identity(self, _identities):
        url = db_url(application=True)
        assert url.username == "applicatif"
        assert url.password == "secret-applicatif"

    def test_migrations_and_pipeline_use_the_schema_owner(self, _identities):
        url = db_url()
        assert url.username == "proprietaire"
        assert url.password == "secret-proprietaire"

    def test_unconfigured_restricted_identity_is_refused(self, monkeypatch):
        # Un repli silencieux sur le propriétaire ferait tourner l'API avec ses droits.
        monkeypatch.setattr(settings, "db_owner_user", "proprietaire")
        monkeypatch.setattr(settings, "db_owner_password", SecretStr("secret-proprietaire"))
        monkeypatch.setattr(settings, "db_app_user", "")
        with pytest.raises(RuntimeError, match="DB_APP_USER"):
            db_url(application=True)

    def test_the_refusal_says_how_to_create_the_role(self, monkeypatch):
        monkeypatch.setattr(settings, "db_app_user", "")
        with pytest.raises(RuntimeError, match="roles.sql"):
            db_url(application=True)
