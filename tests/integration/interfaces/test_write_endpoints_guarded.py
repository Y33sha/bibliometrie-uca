"""Garde d'authentification des écritures, vérifiée sur toutes les routes de l'API.

Le middleware d'`interfaces.api.app` filtre sur la méthode HTTP : une écriture sans session valide est refusée avant tout traitement. Seul le préfixe `/api/auth/` est exempté. Les tests énumèrent les écritures du contrat publié (OpenAPI) : toute écriture du contrat est couverte, et une écriture sous le préfixe exempté fait échouer les tests.

Une route absente du contrat échapperait à cette énumération, mais aussi aux types du frontend qui en dérivent ; le contrôle de fraîcheur de ces types la signalerait.
"""

import re

import pytest

from interfaces.api.app import app

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

AUTH_PREFIX = "/api/auth/"

EXEMPTED_WRITES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
}
"""Seules écritures que le middleware laisse passer sans session : ouvrir et fermer une session.

Toute autre écriture sous le préfixe exempté échapperait à la garde : l'y ajouter suppose de la déclarer ici.
"""

_PATH_PARAM = re.compile(r"\{[^}]+\}")


def _write_endpoints() -> list[tuple[str, str]]:
    """Couples (méthode, chemin) de toutes les écritures du contrat d'API, triés."""
    chemins = app.openapi()["paths"]
    return sorted(
        {
            (methode.upper(), chemin)
            for chemin, operations in chemins.items()
            for methode in operations
            if methode.upper() in WRITE_METHODS
        }
    )


def _concrete(path: str) -> str:
    """Chemin dont chaque paramètre vaut `1` : les identifiants du projet sont des entiers, et la garde refuse avant la validation."""
    return _PATH_PARAM.sub("1", path)


def test_le_contrat_porte_des_ecritures():
    """Une énumération vide ferait passer les tests sans rien vérifier."""
    assert len(_write_endpoints()) > 30


@pytest.mark.parametrize(
    ("methode", "chemin"),
    [couple for couple in _write_endpoints() if couple not in EXEMPTED_WRITES],
)
def test_une_ecriture_sans_session_est_refusee(client, methode, chemin):
    reponse = client.request(methode, _concrete(chemin))
    assert reponse.status_code == 401, (
        f"{methode} {chemin} répond {reponse.status_code} sans session : "
        "la garde d'authentification ne le couvre pas."
    )


@pytest.mark.parametrize(
    ("methode", "chemin"),
    [("POST", "/api/inexistant"), ("DELETE", "/api/inexistant/1")],
)
def test_une_ecriture_sur_un_chemin_inexistant_est_refusee_de_meme(client, methode, chemin):
    """La garde précède le routage : le refus est le même, que le chemin existe ou non.

    Un appelant anonyme ne peut donc pas dresser la liste des écritures.
    """
    assert client.request(methode, chemin).status_code == 401


def test_les_seules_ecritures_exemptees_sont_celles_de_la_session():
    """Les écritures sous le préfixe exempté `/api/auth/` sont exactement celles de `EXEMPTED_WRITES`."""
    sous_le_prefixe = {
        (methode, chemin)
        for methode, chemin in _write_endpoints()
        if chemin.startswith(AUTH_PREFIX)
    }
    assert sous_le_prefixe == EXEMPTED_WRITES
