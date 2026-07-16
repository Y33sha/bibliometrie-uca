"""Service du frontend SvelteKit buildé, monté à la racine par `app.py`."""

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

from infrastructure import PROJECT_ROOT

BUILD_DIR = PROJECT_ROOT / "interfaces" / "frontend" / "build"


class SPAStaticFiles(StaticFiles):
    """Sert le build SvelteKit (adapter-static).

    Deux particularités du format prérendu :

    - les pages prérendues sont écrites en `<route>.html` (par exemple `docs/glossaire.html`) : le chemin nu introuvable est retenté avec l'extension `.html` ;
    - les routes purement client-side (`ssr=false`, non prérendues) retombent sur `index.html`, qui les route côté client.

    Seul le fichier absent (404) déclenche ces reprises ; les autres erreurs remontent, plutôt que de servir `index.html` à leur place.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        candidates = [path] if path.endswith(".html") else [path, f"{path}.html"]
        for candidate in candidates:
            try:
                return await super().get_response(candidate, scope)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        return await super().get_response("index.html", scope)
