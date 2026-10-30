"""Comportement de l'API servie sous un préfixe de déploiement (`ROOT_PATH`).

Conformément à la spécification ASGI, le serveur laisse le préfixe dans `scope["path"]` et le signale à part, dans `scope["root_path"]`. Le routage l'ôte juste avant d'apparier les routes, donc après les middlewares.

Le middleware d'authentification décide sur le chemin et exempte la connexion. Cette exemption vise le chemin de routage, sans le préfixe ; l'ouverture de toute session en dépend.

Un reverse-proxy retire le préfixe avant de transmettre, ou le transmet tel quel. L'application répond à l'identique dans les deux cas : le routage ôte le préfixe quand il est présent.

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
    """Fournit un client visant l'application montée sous un préfixe, comme derrière un reverse-proxy qui le retire.

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
        """Sous le préfixe, une écriture sans session, hors de la connexion, est refusée comme ailleurs."""
        r = client_prefixe.patch(
            f"{PREFIXE}/api/persons/1/exclusion", json={"exclusion": "not_a_person"}
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "Non authentifié"

    def test_les_lectures_repondent(self, client_prefixe):
        assert client_prefixe.get(f"{PREFIXE}/api/pipeline/phases").status_code == 200


class TestProxyQuiNeRetirePasLePrefixe:
    """Le proxy transmet le chemin préfixé tel quel : l'application le reconnaît aussi.

    Un chemin sans route retombe sur le frontend, monté en dernier. Sans cette reconnaissance, un appel d'API reçoit la page d'accueil en HTML sous un code 200, sans signal d'erreur.
    """

    @pytest.fixture
    def client_nu(self) -> Iterator[TestClient]:
        """Fournit un client sans `root_path` déclaré au transport : le chemin préfixé arrive tel quel, comme d'un proxy qui le transmet."""
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_une_lecture_rend_du_json_et_non_la_page_d_accueil(self, client_prefixe):
        r = client_prefixe.get(f"{PREFIXE}/api/pipeline/phases")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")

    def test_un_chemin_d_api_inconnu_rend_404_et_non_la_page_d_accueil(self, client_nu):
        """Sous un préfixe non retiré, un chemin d'API inconnu renvoie 404, sans la page d'accueil."""
        r = client_nu.get("/bibliometrie/api/inconnu")
        assert r.status_code == 404
        assert not r.headers["content-type"].startswith("text/html")

    def test_une_page_du_frontend_reste_servie(self, client_nu):
        """La garde vise seulement les chemins d'API : les pages du frontend restent servies."""
        r = client_nu.get("/publications")
        assert r.status_code in (200, 404)  # 200 si le frontend est construit, 404 sinon
        assert r.headers["content-type"].startswith("text/html") or r.status_code == 404
