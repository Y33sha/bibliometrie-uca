"""Comportement de l'API servie sous un préfixe de déploiement (`ROOT_PATH`).

Le serveur ASGI ne retire pas le préfixe du chemin : conformément à la spécification, il le laisse dans `scope["path"]` et signale à part, dans `scope["root_path"]`, la part qui relève du montage. C'est le routage qui l'ôte, juste avant d'apparier les routes — donc après les middlewares.

Tout code qui décide sur le chemin avant le routage doit donc l'ôter lui-même. Le middleware d'authentification en dépend : il exempte la connexion des écritures gardées, et cette exemption ne joue plus si elle porte sur un chemin encore préfixé — auquel cas personne ne peut ouvrir de session, et l'administration devient inaccessible.

Aucun autre test ne monte l'application sous un préfixe ; c'est ici qu'il se vérifie.
"""

import pytest
from fastapi.testclient import TestClient

from infrastructure.settings import settings
from interfaces.api.app import app

PREFIXE = "/bibliometrie"


@pytest.fixture
def client_prefixe() -> TestClient:
    """Client visant l'application montée sous un préfixe, comme derrière un reverse-proxy qui le retire.

    `TestClient` compose le même `scope` qu'uvicorn lancé avec `--root-path` : chemin complet, préfixe signalé à part.
    """
    with TestClient(app, root_path=PREFIXE, raise_server_exceptions=False) as c:
        yield c


class TestConnexionSousPrefixe:
    def test_la_connexion_atteint_sa_route(self, client_prefixe):
        """Non-régression : l'exemption d'authentification portait sur le chemin préfixé, qu'aucune requête ne présente jamais. La connexion était refusée par le middleware avant d'atteindre sa route, et aucune session ne pouvait plus s'ouvrir.

        Le message distingue les deux refus : « Identifiants incorrects » vient de la route, « Non authentifié » du middleware.
        """
        r = client_prefixe.post(
            f"{PREFIXE}/api/auth/login",
            json={"username": settings.admin_user, "password": "mauvais"},
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "Identifiants incorrects"

    def test_la_deconnexion_atteint_sa_route(self, client_prefixe):
        r = client_prefixe.post(f"{PREFIXE}/api/auth/logout")
        assert r.status_code == 200

    def test_les_ecritures_restent_gardees(self, client_prefixe):
        """Le préfixe ne desserre rien : hors de la connexion, une écriture sans session est refusée comme ailleurs."""
        r = client_prefixe.patch(f"{PREFIXE}/api/persons/1/reject", json={"rejected": True})
        assert r.status_code == 401
        assert r.json()["detail"] == "Non authentifié"

    def test_les_lectures_repondent(self, client_prefixe):
        assert client_prefixe.get(f"{PREFIXE}/api/pipeline/phases").status_code == 200
