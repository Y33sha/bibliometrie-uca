"""Service du frontend SvelteKit compilé, monté à la racine par `app.py`."""

import pathlib

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

from infrastructure import PROJECT_ROOT

BUILD_DIR = PROJECT_ROOT / "interfaces" / "frontend" / "build"

# `StaticFiles` renvoie le chemin relatif au point de montage et normalisé par le système : le séparateur est celui de la plateforme, d'où la comparaison sur les segments.
_API_SEGMENT = "api"


class SPAStaticFiles(StaticFiles):
    """Sert le build SvelteKit (adapter-static).

    Un fichier absent (404) est repris, dans l'ordre :

    - un chemin sans extension est retenté en `<chemin>.html`, forme d'une route prérendue par `adapter-static` ;
    - ce qui reste introuvable retombe sur `index.html`, qui route la demande côté client.

    Les autres erreurs remontent.

    Le repli s'arrête à la frontière de l'API. Monté à la racine, ce service reçoit tout ce qu'aucun router n'a pris, `/api/*` compris : un chemin d'API inconnu renvoie un 404.

    Le segment `api` est reconnu où qu'il se trouve dans le chemin : un préfixe de déploiement laissé en place le décale d'un cran. Aucune page du frontend ne contient ce segment.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        candidates = [path] if path.endswith(".html") else [path, f"{path}.html"]
        for candidate in candidates:
            try:
                return await super().get_response(candidate, scope)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        if _API_SEGMENT in pathlib.PurePath(path).parts:
            raise HTTPException(status_code=404, detail="Not Found")
        return await super().get_response("index.html", scope)
