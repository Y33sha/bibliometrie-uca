"""Jeton de session : signature, expiration et formes illisibles."""

import time

import pytest

from interfaces.api import session as session_module
from interfaces.api.session import SESSION_MAX_AGE, issue_token, read_session


class TestReadSession:
    def test_reads_back_the_user_it_issued(self):
        assert read_session(issue_token("admin")) == "admin"

    def test_rejects_a_tampered_payload(self):
        """Le nom est en clair dans le jeton : seule la signature interdit de le réécrire."""
        token = issue_token("admin")
        payload, signature = token.rsplit(".", 1)
        forged = payload.replace("admin", "pirate", 1) + "." + signature
        assert read_session(forged) is None

    def test_rejects_a_foreign_signature(self, monkeypatch):
        token = issue_token("admin")
        monkeypatch.setattr(session_module.settings, "session_secret", "autre-secret")
        assert read_session(token) is None

    def test_rejects_an_expired_token(self, monkeypatch):
        token = issue_token("admin")
        expired_at = time.time() + SESSION_MAX_AGE + 1
        monkeypatch.setattr(session_module.time, "time", lambda: expired_at)
        assert read_session(token) is None

    @pytest.mark.parametrize("token", ["", "sans-point", "sans-signature.", "payload.signature"])
    def test_rejects_malformed_tokens(self, token):
        assert read_session(token) is None

    def test_reads_a_user_bearing_the_payload_separator(self):
        """Le séparateur est cherché en partant de la fin : l'horodatage est le dernier champ, non le second."""
        assert read_session(issue_token("admin|prod")) == "admin|prod"
