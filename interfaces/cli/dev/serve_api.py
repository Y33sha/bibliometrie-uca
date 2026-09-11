# STATUS: recurring (dev)
"""Lance l'API en développement, avec rechargement à chaud, sur `API_PORT` (8000 par défaut).

Usage :
    python -m interfaces.cli.dev.serve_api
"""

import uvicorn

from infrastructure.settings import settings


def main() -> None:
    uvicorn.run("interfaces.api.app:app", host="127.0.0.1", port=settings.api_port, reload=True)


if __name__ == "__main__":
    main()
