"""Adresse annoncée en polite pool, lue dans l'environnement, et User-Agent qui l'annonce."""

import pytest

from infrastructure.settings import settings
from pipeline.http.polite_pool import (
    default_user_agent,
    get_polite_pool_email,
    get_polite_pool_email_optional,
    polite_user_agent,
)


class TestUserAgent:
    def test_le_user_agent_du_polite_pool_annonce_l_adresse(self, monkeypatch):
        monkeypatch.setattr(settings, "polite_pool_email", "foo@bar.fr")
        assert polite_user_agent() == "BibliometrieUCA-pipeline/1.0 (mailto:foo@bar.fr)"

    def test_le_user_agent_du_polite_pool_exige_l_adresse(self, monkeypatch):
        monkeypatch.setattr(settings, "polite_pool_email", "")
        with pytest.raises(RuntimeError, match="POLITE_POOL_EMAIL"):
            polite_user_agent()

    def test_le_user_agent_par_defaut_annonce_l_adresse_configuree(self, monkeypatch):
        monkeypatch.setattr(settings, "polite_pool_email", "foo@bar.fr")
        assert default_user_agent() == "BibliometrieUCA-pipeline/1.0 (mailto:foo@bar.fr)"

    def test_le_user_agent_par_defaut_se_passe_de_l_adresse(self, monkeypatch):
        """Sans adresse, le `User-Agent` nomme le seul produit, sans `mailto` vide."""
        monkeypatch.setattr(settings, "polite_pool_email", "")
        assert default_user_agent() == "BibliometrieUCA-pipeline/1.0"


class TestAdressePolitePool:
    def test_adresse_configuree(self, monkeypatch):
        monkeypatch.setattr(settings, "polite_pool_email", "contact@uca.fr")

        assert get_polite_pool_email_optional() == "contact@uca.fr"
        assert get_polite_pool_email() == "contact@uca.fr"

    def test_absence_toleree_par_les_appelants_qui_s_en_passent(self, monkeypatch):
        monkeypatch.setattr(settings, "polite_pool_email", "")

        assert get_polite_pool_email_optional() is None

    def test_absence_refusee_par_ceux_qui_l_exigent(self, monkeypatch):
        """Sans adresse configurée, aucune adresse par défaut : une adresse inventée expose à un blocage côté serveur."""
        monkeypatch.setattr(settings, "polite_pool_email", "")

        with pytest.raises(RuntimeError, match="POLITE_POOL_EMAIL"):
            get_polite_pool_email()
