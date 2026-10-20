"""Adresse annoncée en polite pool, lue dans l'environnement, et User-Agent qui l'annonce."""

import pytest

from infrastructure.settings import settings
from pipeline.http.polite_pool import (
    build_user_agent,
    get_polite_pool_email,
    get_polite_pool_email_optional,
)


def test_build_user_agent_includes_email():
    ua = build_user_agent("foo@bar.fr")
    assert "mailto:foo@bar.fr" in ua
    assert "BibliometrieUCA" in ua


class TestAdressePolitePool:
    def test_adresse_configuree(self, monkeypatch):
        monkeypatch.setattr(settings, "polite_pool_email", "contact@uca.fr")

        assert get_polite_pool_email_optional() == "contact@uca.fr"
        assert get_polite_pool_email() == "contact@uca.fr"

    def test_absence_toleree_par_les_appelants_qui_s_en_passent(self, monkeypatch):
        monkeypatch.setattr(settings, "polite_pool_email", "")

        assert get_polite_pool_email_optional() is None

    def test_absence_refusee_par_ceux_qui_l_exigent(self, monkeypatch):
        """Aucune adresse de repli : une adresse inventée expose à un blocage côté serveur."""
        monkeypatch.setattr(settings, "polite_pool_email", "")

        with pytest.raises(RuntimeError, match="POLITE_POOL_EMAIL"):
            get_polite_pool_email()
