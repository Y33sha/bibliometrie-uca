"""Comportement de l'API servie sous un préfixe de déploiement (`ROOT_PATH`).

Le serveur ASGI ne retire pas le préfixe du chemin : conformément à la spécification, il le laisse dans `scope["path"]` et signale à part, dans `scope["root_path"]`, la part qui relève du montage. C'est le routage qui l'ôte, juste avant d'apparier les routes — donc après les middlewares.

Le middleware d'authentification décide sur le chemin, et exempte la connexion des écritures qu'il garde : cette exemption porte sur le chemin de routage, celui privé du préfixe. La connexion en dépend, et l'ouverture de toute session avec elle.

Deux sortes de reverse-proxy existent : celui qui retire le préfixe avant de transmettre, et celui qui le transmet tel quel. L'application répond à l'identique sous les deux, le routage ôtant le préfixe quand il est là et laissant le chemin intact quand il est absent.

Ces tests sont les seuls à monter l'application sous un préfixe.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from infrastructure.settings import settings
from interfaces.api.app import app

PREFIXE = "/bibliometrie"


@pytest.fixture
def client_prefixe() -> Iterator[TestClient]:
    """Client visant l'application montée sous un préfixe, comme derrière un reverse-proxy qui le retire.

    `TestClient` compose le même `scope` qu'uvicorn lancé avec `--root-path` : chemin complet, préfixe signalé à part.
    """
    with TestClient(app, root_path=PREFIXE, raise_server_exceptions=False) as c:
        yield c


class TestConnexionSousPrefixe:
    def test_la_connexion_atteint_sa_route(self, client_prefixe):
        """La requête traverse le middleware qui garde les écritures et atteint la route de connexion.

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


class TestProxyQuiNeRetirePasLePrefixe:
    """Le proxy transmet le chemin préfixé tel quel : l'application doit le reconnaître aussi.

    Non-régression sur une panne muette : quand le chemin ne correspond à aucune route, la requête retombe sur le service du frontend monté en dernier recours, et un appel d'API reçoit la page d'accueil sous un code 200 — le client attend du JSON, reçoit du HTML, et rien ne signale l'erreur.
    """

    @pytest.fixture
    def client_nu(self) -> Iterator[TestClient]:
        """Client sans `root_path` déclaré au transport : le chemin préfixé arrive tel quel, comme d'un proxy qui le transmet."""
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_une_lecture_rend_du_json_et_non_la_page_d_accueil(self, client_prefixe):
        r = client_prefixe.get(f"{PREFIXE}/api/pipeline/phases")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")

    def test_un_chemin_d_api_inconnu_rend_404_et_non_la_page_d_accueil(self, client_nu):
        """Même décalé par un préfixe mal retiré, un chemin d'API est reconnu comme tel."""
        r = client_nu.get("/bibliometrie/api/inconnu")
        assert r.status_code == 404
        assert not r.headers["content-type"].startswith("text/html")

    def test_une_page_du_frontend_reste_servie(self, client_nu):
        """La garde ne mord que sur les chemins d'API : aucune page du frontend ne porte ce segment."""
        r = client_nu.get("/publications")
        assert r.status_code in (200, 404)  # 200 avec un frontend buildé, 404 sans
        assert r.headers["content-type"].startswith("text/html") or r.status_code == 404
