"""Confinement des valeurs secrètes de la configuration.

Les mots de passe, la clé de signature des sessions et les identifiants d'accès aux sources sont typés `SecretStr` : un relevé de la configuration, une trace d'erreur ou un journal qui traverserait l'objet rend un masque, et la valeur se lit par un appel explicite.
"""

from pydantic import SecretStr

from infrastructure.settings import Settings, settings

CHAMPS_SECRETS = [
    "admin_hash",
    "session_secret",
    "db_owner_password",
    "db_app_password",
    "openalex_api_key",
    "wos_api_key",
    "scanr_password",
]


class TestTypage:
    def test_les_champs_secrets_sont_des_secrets(self):
        for nom in CHAMPS_SECRETS:
            assert isinstance(getattr(settings, nom), SecretStr), nom

    def test_les_identifiants_publics_restent_en_clair(self):
        # Un nom d'utilisateur ou une adresse d'hôte se lit dans une trace sans dommage, et
        # le masquer gênerait le diagnostic.
        for nom in ("admin_user", "db_app_user", "db_owner_user", "db_host", "scanr_username"):
            assert isinstance(getattr(settings, nom), str), nom


class TestMasquage:
    def _config(self) -> Settings:
        return Settings(
            admin_hash="empreinte-a-ne-pas-divulguer",
            session_secret="cle-de-signature-a-ne-pas-divulguer",
            db_owner_password="mot-de-passe-proprietaire",
            db_app_password="mot-de-passe-applicatif",
            openalex_api_key="cle-openalex",
            wos_api_key="cle-wos",
            scanr_password="mot-de-passe-scanr",
        )  # type: ignore[call-arg]

    def test_la_representation_ne_porte_aucune_valeur(self):
        rendu = repr(self._config())
        for valeur in (
            "empreinte-a-ne-pas-divulguer",
            "cle-de-signature-a-ne-pas-divulguer",
            "mot-de-passe-proprietaire",
            "mot-de-passe-applicatif",
            "cle-openalex",
            "cle-wos",
            "mot-de-passe-scanr",
        ):
            assert valeur not in rendu

    def test_la_serialisation_ne_porte_aucune_valeur(self):
        rendu = str(self._config().model_dump())
        assert "cle-de-signature-a-ne-pas-divulguer" not in rendu
        assert "mot-de-passe-applicatif" not in rendu

    def test_la_valeur_se_lit_explicitement(self):
        config = self._config()
        assert config.session_secret.get_secret_value() == "cle-de-signature-a-ne-pas-divulguer"
