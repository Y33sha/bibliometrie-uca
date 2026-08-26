"""Choix de l'identité de connexion : l'API se connecte au rôle restreint, le reste au propriétaire du schéma."""

import pytest

from infrastructure.db.engine import db_url
from infrastructure.settings import settings


@pytest.fixture
def _identities(monkeypatch):
    monkeypatch.setattr(settings, "db_owner_user", "proprietaire")
    monkeypatch.setattr(settings, "db_owner_password", "secret-proprietaire")
    monkeypatch.setattr(settings, "db_app_user", "applicatif")
    monkeypatch.setattr(settings, "db_app_password", "secret-applicatif")


class TestConnectionIdentity:
    def test_api_uses_the_restricted_identity(self, _identities):
        url = db_url(application=True)
        assert url.username == "applicatif"
        assert url.password == "secret-applicatif"

    def test_migrations_and_pipeline_use_the_schema_owner(self, _identities):
        url = db_url()
        assert url.username == "proprietaire"
        assert url.password == "secret-proprietaire"

    def test_unconfigured_restricted_identity_falls_back_to_the_owner(self, monkeypatch):
        # Poste de développement : une seule identité, l'API se connecte comme le reste.
        monkeypatch.setattr(settings, "db_owner_user", "proprietaire")
        monkeypatch.setattr(settings, "db_owner_password", "secret-proprietaire")
        monkeypatch.setattr(settings, "db_app_user", "")
        monkeypatch.setattr(settings, "db_app_password", "")
        assert db_url(application=True).username == "proprietaire"
