"""Service du frontend buildé : reprises sur fichier absent, et frontière de l'API.

Trois comportements distinguent ce service d'un service de fichiers statiques ordinaire. Un chemin introuvable est retenté avec l'extension `.html` (pages prérendues). Une route inconnue retombe sur `index.html` (routage côté client). Un chemin d'API inconnu reçoit un 404 : la page d'accueil, servie sous un code 200, ferait passer une panne d'API pour un succès.

Une erreur autre qu'un fichier absent remonte telle quelle : les reprises valent seulement pour le 404.
"""

from collections.abc import Set as AbstractSet
from unittest.mock import patch

import pytest
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse

from interfaces.api.spa import SPAStaticFiles

_SCOPE = {"type": "http", "method": "GET"}


def _service_de_fichiers(*, disponibles: AbstractSet[str] = frozenset(), erreur: int | None = None):
    """Simule le service de fichiers sous-jacent : seuls les chemins `disponibles` existent.

    `erreur` fait échouer tout accès avec ce code, pour tester une erreur autre qu'un fichier absent.
    """
    servis: list[str] = []

    async def _get_response(self, path: str, scope):
        servis.append(path)
        if erreur is not None:
            raise HTTPException(status_code=erreur)
        if path not in disponibles:
            raise HTTPException(status_code=404)
        return PlainTextResponse(path)

    return patch.object(StaticFiles, "get_response", _get_response), servis


async def test_page_prerendue_retentee_avec_l_extension():
    correctif, servis = _service_de_fichiers(disponibles={"docs/glossaire.html"})
    with correctif:
        reponse = await SPAStaticFiles(directory=".", check_dir=False).get_response(
            "docs/glossaire", _SCOPE
        )

    assert reponse.body == b"docs/glossaire.html"
    assert servis == ["docs/glossaire", "docs/glossaire.html"]


async def test_route_inconnue_retombe_sur_la_page_d_accueil():
    correctif, _ = _service_de_fichiers(disponibles={"index.html"})
    with correctif:
        reponse = await SPAStaticFiles(directory=".", check_dir=False).get_response(
            "publications/42", _SCOPE
        )

    assert reponse.body == b"index.html"


@pytest.mark.parametrize("chemin", ["api/inconnu", "prefixe/api/inconnu"])
async def test_chemin_d_api_inconnu_rend_404(chemin):
    """Le segment `api` est reconnu à toute position : un préfixe de déploiement le place en deuxième position."""
    correctif, _ = _service_de_fichiers(disponibles={"index.html"})
    with correctif, pytest.raises(HTTPException) as refus:
        await SPAStaticFiles(directory=".", check_dir=False).get_response(chemin, _SCOPE)

    assert refus.value.status_code == 404


async def test_erreur_autre_qu_un_fichier_absent_remonte():
    correctif, servis = _service_de_fichiers(erreur=403)
    with correctif, pytest.raises(HTTPException) as remontee:
        await SPAStaticFiles(directory=".", check_dir=False).get_response("page", _SCOPE)

    assert remontee.value.status_code == 403
    assert servis == ["page"]  # aucune reprise tentée
