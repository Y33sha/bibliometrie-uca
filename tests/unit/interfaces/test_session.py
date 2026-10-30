"""Jeton de session : signature, expiration et formes illisibles."""

import time

import bcrypt
import pytest
from pydantic import SecretStr

from interfaces.api import session as session_module
from interfaces.api.session import (
    SESSION_MAX_AGE,
    check_password,
    issue_token,
    read_session,
)


class TestReadSession:
    def test_reads_back_the_user_it_issued(self):
        assert read_session(issue_token("admin")) == "admin"

    def test_rejects_a_tampered_payload(self):
        """Le nom est en clair dans le jeton ; seule la signature empêche de le réécrire."""
        token = issue_token("admin")
        payload, signature = token.rsplit(".", 1)
        forged = payload.replace("admin", "pirate", 1) + "." + signature
        assert read_session(forged) is None

    def test_rejects_a_foreign_signature(self, monkeypatch):
        token = issue_token("admin")
        monkeypatch.setattr(session_module.settings, "session_secret", SecretStr("autre-secret"))
        assert read_session(token) is None

    def test_rejects_an_expired_token(self, monkeypatch):
        token = issue_token("admin")
        expired_at = time.time() + SESSION_MAX_AGE + 1
        monkeypatch.setattr(session_module.time, "time", lambda: expired_at)
        assert read_session(token) is None

    @pytest.mark.parametrize("token", ["", "sans-point", "sans-signature.", "payload.signature"])
    def test_rejects_malformed_tokens(self, token):
        assert read_session(token) is None

    def test_rejects_a_signed_payload_without_a_timestamp(self):
        """Un jeton bien signé, sans horodatage, est refusé.

        Le jeton est signé avec la clé du service : la signature est vérifiée d'abord, et seul un jeton bien signé atteint le contrôle de forme.
        """
        payload = "admin"
        assert read_session(f"{payload}.{session_module._sign(payload)}") is None

    def test_rejects_a_signed_payload_whose_timestamp_is_not_a_number(self):
        payload = f"admin{session_module._PAYLOAD_SEPARATOR}hier"
        assert read_session(f"{payload}.{session_module._sign(payload)}") is None

    def test_reads_a_user_bearing_the_payload_separator(self):
        """Le séparateur est cherché à partir de la fin : l'horodatage est le dernier champ, et le nom peut contenir le séparateur."""
        assert read_session(issue_token("admin|prod")) == "admin|prod"


class TestCheckPassword:
    def test_accepts_the_matching_password_and_rejects_others(self, monkeypatch):
        hashed = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
        monkeypatch.setattr(session_module.settings, "admin_hash", SecretStr(hashed))
        assert check_password("secret") is True
        assert check_password("mauvais") is False

    def test_rejects_a_malformed_hash_without_erroring(self, monkeypatch):
        """Un hash mal formé (valeur d'exemple de la configuration) refuse la connexion, sans erreur serveur."""
        monkeypatch.setattr(session_module.settings, "admin_hash", SecretStr("pas-un-hash-bcrypt"))
        assert check_password("peu importe") is False

    def test_rejects_when_no_hash_configured(self, monkeypatch):
        monkeypatch.setattr(session_module.settings, "admin_hash", SecretStr(""))
        assert check_password("peu importe") is False
