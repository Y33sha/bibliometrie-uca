"""Confinement des valeurs secrètes de la configuration.

Les mots de passe, la clé de signature des sessions et les identifiants d'accès aux sources sont typés `SecretStr`. Leur représentation et leur sérialisation affichent un masque ; la valeur se lit par un appel explicite.
"""

import re

from pydantic import SecretStr

from infrastructure.settings import Settings, settings

# Un champ dont le nom désigne un secret : mot de passe, clé, empreinte ou secret de session.
_NOM_DE_SECRET = re.compile(r"(password|secret|key|hash)$")

CHAMPS_SECRETS = [nom for nom in Settings.model_fields if _NOM_DE_SECRET.search(nom)]


class TestTypage:
    def test_les_champs_secrets_sont_des_secrets(self):
        for nom in CHAMPS_SECRETS:
            assert isinstance(getattr(settings, nom), SecretStr), nom

    def test_seuls_les_champs_secrets_sont_masques(self):
        masques = [
            nom for nom, champ in Settings.model_fields.items() if champ.annotation is SecretStr
        ]
        assert sorted(masques) == sorted(CHAMPS_SECRETS)

    def test_les_identifiants_publics_restent_en_clair(self):
        # Un nom d'utilisateur ou une adresse d'hôte se lit dans une trace sans dommage ; le masquer gênerait le diagnostic.
        for nom in (
            "admin_user",
            "db_app_user",
            "db_owner_user",
            "db_pipeline_user",
            "db_host",
            "scanr_username",
        ):
            assert isinstance(getattr(settings, nom), str), nom


class TestMasquage:
    def _config(self) -> Settings:
        return Settings(**{nom: f"valeur-de-{nom}" for nom in CHAMPS_SECRETS})  # type: ignore[arg-type]

    def test_la_representation_ne_porte_aucune_valeur(self):
        rendu = repr(self._config())
        for nom in CHAMPS_SECRETS:
            assert f"valeur-de-{nom}" not in rendu

    def test_la_serialisation_ne_porte_aucune_valeur(self):
        rendu = str(self._config().model_dump())
        for nom in CHAMPS_SECRETS:
            assert f"valeur-de-{nom}" not in rendu

    def test_la_valeur_se_lit_explicitement(self):
        config = self._config()
        assert config.session_secret.get_secret_value() == "valeur-de-session_secret"
