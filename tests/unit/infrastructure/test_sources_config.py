"""Configuration des sources : secrets d'accès, et robustesse aux pannes de lecture.

Les identifiants d'accès aux API viennent de l'environnement, non de la base : ce sont des secrets. Leur absence se traduit différemment selon la source — une valeur vide, un couple vide, ou un refus net pour l'adresse annoncée en polite pool, qu'aucune valeur inventée ne doit remplacer.

Une panne de lecture en base ne fait pas échouer le pipeline : le réglage retombe sur son défaut, et l'incident est signalé.
"""

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from infrastructure.sources import config as module
from infrastructure.sources.config import (
    get_extraction_api_ids,
    get_hal_collections,
    get_openalex_api_key,
    get_polite_pool_email,
    get_polite_pool_email_optional,
    get_scanr_credentials,
    get_wos_api_key,
)


class TestSecretsDAcces:
    def test_cle_openalex_absente(self, monkeypatch):
        monkeypatch.setattr(module.settings, "openalex_api_key", SecretStr(""))
        assert get_openalex_api_key() is None

    def test_cle_openalex_presente(self, monkeypatch):
        monkeypatch.setattr(module.settings, "openalex_api_key", SecretStr("clé"))
        assert get_openalex_api_key() == "clé"

    def test_cle_wos(self, monkeypatch):
        monkeypatch.setattr(module.settings, "wos_api_key", SecretStr("clé-wos"))
        assert get_wos_api_key() == "clé-wos"

    def test_identifiants_scanr_complets(self, monkeypatch):
        monkeypatch.setattr(module.settings, "scanr_username", "utilisateur")
        monkeypatch.setattr(module.settings, "scanr_password", SecretStr("secret"))
        assert get_scanr_credentials() == ("utilisateur", "secret")

    @pytest.mark.parametrize(
        ("utilisateur", "secret"), [("utilisateur", ""), ("", "secret"), ("", "")]
    )
    def test_identifiants_scanr_incomplets(self, monkeypatch, utilisateur, secret):
        """Un identifiant sans son mot de passe ne vaut rien : le couple entier est tenu pour absent."""
        monkeypatch.setattr(module.settings, "scanr_username", utilisateur)
        monkeypatch.setattr(module.settings, "scanr_password", SecretStr(secret))
        assert get_scanr_credentials() == ("", "")


class TestAdressePolitePool:
    def test_adresse_configuree(self, monkeypatch):
        monkeypatch.setattr(module.settings, "polite_pool_email", "contact@uca.fr")

        assert get_polite_pool_email_optional() == "contact@uca.fr"
        assert get_polite_pool_email() == "contact@uca.fr"

    def test_absence_toleree_par_les_appelants_qui_s_en_passent(self, monkeypatch):
        monkeypatch.setattr(module.settings, "polite_pool_email", "")

        assert get_polite_pool_email_optional() is None

    def test_absence_refusee_par_ceux_qui_l_exigent(self, monkeypatch):
        """Aucune adresse de repli : une adresse inventée expose à un blocage côté serveur."""
        monkeypatch.setattr(module.settings, "polite_pool_email", "")

        with pytest.raises(RuntimeError, match="POLITE_POOL_EMAIL"):
            get_polite_pool_email()


class _ConnEnPanne:
    """Connexion dont toute lecture échoue."""

    def execute(self, *args, **kwargs):
        raise SQLAlchemyError("base indisponible")


class _ConnPartielle:
    """Connexion qui répond à la lecture de configuration, puis échoue.

    Reproduit une panne survenant après la lecture du périmètre : c'est la requête sur les structures qui tombe.
    """

    def __init__(self, valeur: str) -> None:
        self._valeur = valeur
        self._premiere = True

    def execute(self, *args, **kwargs):
        if self._premiere:
            self._premiere = False
            return _UneLigne(self._valeur)
        raise SQLAlchemyError("base indisponible")


class _UneLigne:
    def __init__(self, valeur) -> None:
        self._valeur = valeur

    def one_or_none(self):
        return type("Row", (), {"value": self._valeur})()


class TestPanneDeLecture:
    def test_collections_hal_retombent_sur_rien(self):
        assert get_hal_collections(_ConnEnPanne()) == {}

    def test_identifiants_d_api_retombent_sur_rien(self):
        assert get_extraction_api_ids(_ConnEnPanne(), "openalex") == []

    def test_panne_apres_lecture_du_perimetre(self):
        assert get_extraction_api_ids(_ConnPartielle("un_perimetre"), "openalex") == []
