"""Garde d'authentification des écritures, vérifiée sur l'ensemble de la surface d'API.

Le middleware d'`interfaces.api.app` filtre sur la méthode HTTP : une requête d'écriture sans session valide reçoit un refus avant tout traitement, et seul le préfixe `/api/auth/` y échappe. Ces tests confrontent la règle au contrat d'API entier plutôt qu'à des points d'entrée choisis : une écriture ajoutée plus tard est couverte sans qu'on y pense, et une écriture ajoutée sous le préfixe exempté fait échouer l'intégration.

L'énumération part du contrat publié (OpenAPI), qui décrit la surface telle qu'elle est servie. Un point d'entrée soustrait au contrat lui échapperait ; il échapperait du même coup aux types du frontend, qui en dérivent, et le contrôle de fraîcheur de ces types le signalerait.
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
"""Écritures que le middleware laisse passer sans session, et les seules.

Ouvrir une session et la fermer sont les deux gestes qu'on ne peut pas exiger d'une session ouverte. Toute autre écriture sous ce préfixe échapperait à la garde : l'y inscrire est une décision, que ce test rend explicite.
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
    """Chemin où chaque paramètre est remplacé par `1` : les identifiants du projet sont des entiers, et la garde tombe de toute façon avant la validation."""
    return _PATH_PARAM.sub("1", path)


def test_le_contrat_porte_des_ecritures():
    """Filet du filet : une énumération vide passerait sans rien vérifier."""
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


def test_les_seules_ecritures_exemptees_sont_celles_de_la_session():
    """Le préfixe `/api/auth/` échappe à la garde : ce qu'il abrite est énuméré."""
    sous_le_prefixe = {
        (methode, chemin)
        for methode, chemin in _write_endpoints()
        if chemin.startswith(AUTH_PREFIX)
    }
    assert sous_le_prefixe == EXEMPTED_WRITES
