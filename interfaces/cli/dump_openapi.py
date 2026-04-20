"""Dump le schéma OpenAPI de l'API FastAPI vers un fichier JSON.

Utilisé pour alimenter `openapi-typescript` (génération des types côté
frontend) sans nécessiter un backend en cours d'exécution.

Usage :
    python -m interfaces.cli.dump_openapi [output_path]

Défaut de `output_path` : interfaces/frontend/openapi.json
"""

import json
import sys
from pathlib import Path


def main() -> None:
    from interfaces.api.app import app

    default_out = Path(__file__).resolve().parent.parent / "frontend" / "openapi.json"
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_out

    openapi = app.openapi()
    out_path.write_text(json.dumps(openapi, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OpenAPI schema -> {out_path}")


if __name__ == "__main__":
    main()
