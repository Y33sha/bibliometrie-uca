# STATUS: recurring (dev)
"""Dump le schéma OpenAPI de l'API FastAPI vers un fichier JSON.

Utilisé pour alimenter `openapi-typescript` (génération des types côté frontend) sans exiger un backend en cours d'exécution. Lancé par le script npm `types:gen` (cf. `interfaces/frontend/package.json`).

Usage :
    python -m interfaces.cli.dev.dump_openapi [output_path]

Défaut de `output_path` : interfaces/frontend/openapi.json
"""

import json
import sys
from pathlib import Path


def main() -> None:
    from interfaces.api.app import app

    interfaces_dir = Path(__file__).resolve().parents[2]
    default_out = interfaces_dir / "frontend" / "openapi.json"
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_out

    openapi = app.openapi()
    out_path.write_text(json.dumps(openapi, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OpenAPI schema -> {out_path}")


if __name__ == "__main__":
    main()
