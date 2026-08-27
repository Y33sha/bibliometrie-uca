"""Contrôle au démarrage de l'API : de quoi authentifier une session d'administration.

`ADMIN_HASH` et `SESSION_SECRET` sont exigés du processus qui sert l'API, seul à ouvrir des sessions. Le pipeline et les scripts de maintenance lisent la même configuration et démarrent sans eux.
"""

import pytest

from interfaces.api import session as session_mod
from interfaces.api.session import MIN_SESSION_SECRET_LENGTH, check_auth_config

_HASH = "$2b$12$" + "x" * 53
_SECRET = "s" * MIN_SESSION_SECRET_LENGTH


@pytest.fixture
def auth_settings(monkeypatch):
    """Pose une configuration d'authentification valide, que chaque test dégrade sur un point."""

    def _apply(**overrides):
        for name, value in {"admin_hash": _HASH, "session_secret": _SECRET, **overrides}.items():
            monkeypatch.setattr(session_mod.settings, name, value)

    return _apply


def test_configuration_complete_passe(auth_settings):
    auth_settings()
    assert check_auth_config() is None


def test_refuse_sans_empreinte_de_mot_de_passe(auth_settings):
    auth_settings(admin_hash="")
    with pytest.raises(RuntimeError, match="ADMIN_HASH"):
        check_auth_config()


def test_refuse_une_cle_de_signature_absente(auth_settings):
    auth_settings(session_secret="")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        check_auth_config()


def test_refuse_une_cle_de_signature_trop_courte(auth_settings):
    """Une clé courte se retrouve hors ligne, et le jeton de session se forge alors sans mot de passe."""
    auth_settings(session_secret="s" * (MIN_SESSION_SECRET_LENGTH - 1))
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        check_auth_config()


def test_accepte_la_longueur_plancher(auth_settings):
    auth_settings(session_secret="s" * MIN_SESSION_SECRET_LENGTH)
    assert check_auth_config() is None
