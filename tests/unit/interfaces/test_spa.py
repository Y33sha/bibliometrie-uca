"""Service du frontend buildé : reprises sur fichier absent, et frontière de l'API.

Trois comportements distinguent ce service d'un service de fichiers statiques ordinaire : le chemin nu introuvable est retenté avec l'extension `.html` (format prérendu), une route inconnue retombe sur `index.html` (routage côté client), et un chemin d'API inconnu reçoit un 404 plutôt que la page d'accueil — servir celle-ci sous un code 200 ferait passer une panne d'API pour un succès.

Une erreur qui n'est pas un fichier absent remonte telle quelle : les reprises ne valent que pour le 404.
"""

from unittest.mock import patch

import pytest
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse

from interfaces.api.spa import SPAStaticFiles

_SCOPE = {"type": "http", "method": "GET"}


def _service_de_fichiers(*, disponibles: set[str] = frozenset(), erreur: int | None = None):
    """Remplace le service de fichiers sous-jacent : seuls `disponibles` existent.

    `erreur` fait échouer tout accès sur ce code, pour éprouver ce qui n'est pas un fichier absent.
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
    """Le segment est reconnu où qu'il se trouve : un préfixe de déploiement le décale d'un cran."""
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
