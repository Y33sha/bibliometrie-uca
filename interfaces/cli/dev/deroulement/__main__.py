# STATUS: recurring (dev)
"""Régénère la page du déroulement du pipeline, publiée avec la documentation.

Usage :
    uv run python -m interfaces.cli.dev.deroulement [--fragment CHEMIN]

`--fragment` écrit aussi le contenu de la page sans squelette HTML, pour un aperçu hors de la documentation.
"""

import argparse
import sys
from pathlib import Path

from interfaces.cli.dev.deroulement.page import DOC_PAGE, document, fragment, problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Régénère la page du déroulement du pipeline.")
    parser.add_argument(
        "--fragment", type=Path, help="chemin du contenu de la page sans squelette HTML"
    )
    args = parser.parse_args()
    found = problems()
    if found:
        sys.exit("\n".join(found))
    DOC_PAGE.write_text(document())
    print(f"{DOC_PAGE} régénérée")
    if args.fragment:
        args.fragment.write_text(fragment())
        print(f"{args.fragment} régénéré")


if __name__ == "__main__":
    main()
