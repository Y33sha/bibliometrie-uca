"""Page du déroulement du pipeline, composée de `etapes.py`, `descriptions.py` et `template.html`."""

from __future__ import annotations

import json
from pathlib import Path

from interfaces.cli.dev.deroulement import etapes
from interfaces.cli.dev.deroulement.descriptions import SHORT

TEMPLATE = Path(__file__).with_name("template.html")
DOC_PAGE = Path(__file__).resolve().parents[4] / "docs" / "pipeline" / "deroulement.html"
"""Page publiée avec la documentation, à côté de la vue d'ensemble du pipeline."""

_DATA = "/*DATA*/null"
_BACK = "<!--RETOUR-->"
_BACK_LINK = '<a class="back" href="01-vue-d-ensemble/">Vue d\'ensemble du pipeline</a>'


def problems() -> list[str]:
    """Renvoie les tâches mal rangées (`etapes.placement_problems`) et les tâches rangées sans description."""
    undescribed = [f"tâche sans description : {t}" for t in etapes.placed_tasks() if t not in SHORT]
    return etapes.placement_problems() + undescribed


def fragment() -> str:
    """Renvoie le contenu de la page, sans squelette HTML."""
    data = {
        "nodes": etapes.NODES,
        "affluents": etapes.AFFLUENTS,
        "layout": etapes.LAYOUT,
        "edges": etapes.EDGES,
        "descriptions": {t: SHORT[t] for t in etapes.placed_tasks()},
    }
    return TEMPLATE.read_text().replace(_DATA, json.dumps(data, ensure_ascii=False))


def document() -> str:
    """Renvoie la page de la documentation : squelette HTML, thème clair du site, lien vers la vue d'ensemble."""
    body = fragment().replace(_BACK, _BACK_LINK)
    return (
        '<!doctype html>\n<html lang="fr" data-theme="light">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<style>body { margin: 0; }</style>\n</head>\n<body>\n"
        f"{body}\n</body>\n</html>\n"
    )
