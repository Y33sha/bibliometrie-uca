"""Identités de connexion : chaque usage exige la sienne, et refuse de se replier sur l'autre.

Non-régression : `DB_OWNER_USER` n'est plus exigé par les settings, pour qu'un processus qui ne sert que l'API n'ait pas à porter le mot de passe du propriétaire du schéma. L'exigence tient donc au point d'usage, symétriquement à celle qui pesait déjà sur l'identité restreinte.
"""

import pytest

from infrastructure.db import engine as engine_mod
from infrastructure.db.engine import db_url


@pytest.fixture
def db_settings(monkeypatch):
    def _apply(**overrides):
        defaults = {
            "db_app_user": "bibliometrie_app",
            "db_app_password": "app-pw",
            "db_owner_user": "bibliometrie_owner",
            "db_owner_password": "owner-pw",
        }
        for name, value in {**defaults, **overrides}.items():
            monkeypatch.setattr(engine_mod.settings, name, value)

    return _apply


def test_connexion_de_l_api_sous_l_identite_restreinte(db_settings):
    db_settings()
    assert db_url(application=True).username == "bibliometrie_app"


def test_connexion_des_migrations_sous_le_proprietaire(db_settings):
    db_settings()
    assert db_url().username == "bibliometrie_owner"


def test_l_api_refuse_de_demarrer_sans_identite_restreinte(db_settings):
    """Se replier sur le propriétaire ferait tourner l'API avec les droits du schéma sans que rien ne le signale."""
    db_settings(db_app_user="")
    with pytest.raises(RuntimeError, match="DB_APP_USER"):
        db_url(application=True)


def test_les_autres_usages_refusent_de_demarrer_sans_proprietaire(db_settings):
    """Symétrique : un processus qui ne sert que l'API ne porte pas cette identité, et son absence doit se voir plutôt qu'ouvrir une connexion anonyme."""
    db_settings(db_owner_user="")
    with pytest.raises(RuntimeError, match="DB_OWNER_USER"):
        db_url()


def test_l_api_n_a_pas_besoin_du_proprietaire(db_settings):
    """Le partage tient à cela : le conteneur qui sert l'API se passe du mot de passe du schéma."""
    db_settings(db_owner_user="", db_owner_password="")
    assert db_url(application=True).username == "bibliometrie_app"
