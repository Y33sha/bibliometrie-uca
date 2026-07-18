"""Service du frontend SvelteKit buildé, monté à la racine par `app.py`."""

import pathlib

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

from infrastructure import PROJECT_ROOT

BUILD_DIR = PROJECT_ROOT / "interfaces" / "frontend" / "build"

# `StaticFiles` rend le chemin relatif au point de montage et normalisé par le système :
# le séparateur est celui de la plateforme, d'où la comparaison sur les segments.
_API_SEGMENT = "api"


class SPAStaticFiles(StaticFiles):
    """Sert le build SvelteKit (adapter-static).

    Deux particularités du format prérendu :

    - les pages prérendues sont écrites en `<route>.html` (par exemple `docs/glossaire.html`) : le chemin nu introuvable est retenté avec l'extension `.html` ;
    - les routes purement client-side (`ssr=false`, non prérendues) retombent sur `index.html`, qui les route côté client.

    Seul le fichier absent (404) déclenche ces reprises ; les autres erreurs remontent, plutôt que de servir `index.html` à leur place.

    Le repli s'arrête à la frontière de l'API. Monté à la racine, ce service reçoit tout ce qu'aucun router n'a pris, `/api/*` compris : un chemin d'API inconnu doit rendre un 404, non la page d'accueil du frontend sous un code 200.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        candidates = [path] if path.endswith(".html") else [path, f"{path}.html"]
        for candidate in candidates:
            try:
                return await super().get_response(candidate, scope)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        if pathlib.PurePath(path).parts[:1] == (_API_SEGMENT,):
            raise HTTPException(status_code=404, detail="Not Found")
        return await super().get_response("index.html", scope)
