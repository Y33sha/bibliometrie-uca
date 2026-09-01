"""Identités de connexion : chaque usage exige la sienne, et refuse de se replier sur une autre.

Les migrations se connectent sous le propriétaire du schéma, l'API sous son rôle restreint, le pipeline et les scripts en ligne de commande sous le leur. Chaque exigence tient au point d'usage, de sorte qu'un processus porte les seuls identifiants qu'il exerce.
"""

import pytest
from pydantic import SecretStr

from infrastructure.db import engine as engine_mod
from infrastructure.db.engine import db_url


@pytest.fixture
def db_settings(monkeypatch):
    """Pose les trois identités, que chaque test dégrade sur un point."""

    def _apply(**overrides):
        defaults = {
            "db_app_user": "bibliometrie_app",
            "db_app_password": "app-pw",
            "db_owner_user": "bibliometrie_owner",
            "db_owner_password": "owner-pw",
            "db_pipeline_user": "bibliometrie_pipeline",
            "db_pipeline_password": "pipeline-pw",
        }
        for name, value in {**defaults, **overrides}.items():
            # Les mots de passe sont typés `SecretStr` : les poser en clair les rendrait
            # inutilisables par le constructeur d'URL, qui lit par `.get_secret_value()`.
            posee = SecretStr(value) if name.endswith("_password") else value
            monkeypatch.setattr(engine_mod.settings, name, posee)

    return _apply


class TestIdentiteRetenue:
    def test_l_api_se_connecte_sous_son_role_restreint(self, db_settings):
        db_settings()
        url = db_url("app")
        assert url.username == "bibliometrie_app"
        assert url.password == "app-pw"

    def test_les_migrations_se_connectent_sous_le_proprietaire(self, db_settings):
        db_settings()
        url = db_url("owner")
        assert url.username == "bibliometrie_owner"
        assert url.password == "owner-pw"

    def test_le_pipeline_se_connecte_sous_son_role(self, db_settings):
        db_settings()
        url = db_url("pipeline")
        assert url.username == "bibliometrie_pipeline"
        assert url.password == "pipeline-pw"

    def test_le_pipeline_est_l_identite_par_defaut(self, db_settings):
        """Le pipeline et les scripts sont les appelants les plus nombreux ; l'API et les migrations demandent la leur."""
        db_settings()
        assert db_url().username == "bibliometrie_pipeline"


class TestRefusDUneIdentiteAbsente:
    @pytest.mark.parametrize(
        ("identite", "reglage", "variable"),
        [
            ("app", "db_app_user", "DB_APP_USER"),
            ("owner", "db_owner_user", "DB_OWNER_USER"),
            ("pipeline", "db_pipeline_user", "DB_PIPELINE_USER"),
        ],
    )
    def test_une_identite_absente_est_refusee(self, db_settings, identite, reglage, variable):
        """Se replier sur une autre ferait tourner un processus avec des droits qu'il n'exerce pas, sans que rien ne le signale."""
        db_settings(**{reglage: ""})
        with pytest.raises(RuntimeError, match=variable):
            db_url(identite)

    def test_le_refus_indique_comment_creer_le_role(self, db_settings):
        db_settings(db_app_user="")
        with pytest.raises(RuntimeError, match="roles.sql"):
            db_url("app")

    def test_l_api_n_a_besoin_ni_du_proprietaire_ni_du_pipeline(self, db_settings):
        """Le partage tient à cela : le conteneur qui sert l'API se passe des deux autres mots de passe."""
        db_settings(db_owner_user="", db_owner_password="", db_pipeline_user="")
        assert db_url("app").username == "bibliometrie_app"

    def test_le_pipeline_n_a_pas_besoin_du_proprietaire(self, db_settings):
        """Symétrique, et c'est l'objet du rôle : le conteneur qui exécute le pipeline ne porte plus le mot de passe capable de modifier la structure."""
        db_settings(db_owner_user="", db_owner_password="")
        assert db_url("pipeline").username == "bibliometrie_pipeline"
