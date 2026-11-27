"""Page du déroulement du pipeline, composée de `etapes.py`, `descriptions.py` et `template.html`."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pipeline.phases as pipeline_phases
from interfaces.cli.dev.deroulement import etapes
from interfaces.cli.dev.deroulement.descriptions import SHORT
from pipeline.graph import Phase

TEMPLATE = Path(__file__).with_name("template.html")
DOCS_DIR = Path(__file__).resolve().parents[4] / "docs" / "pipeline"
"""Chapitres du pipeline dans la documentation ; les liens `doc` de `etapes.py` y renvoient."""
DOC_PAGE = DOCS_DIR / "deroulement.html"
"""Page publiée avec la documentation, à côté de la vue d'ensemble du pipeline."""

_DATA = "/*DATA*/null"
_BACK = "<!--RETOUR-->"
_BACK_LINK = '<a class="back" href="01-vue-d-ensemble/">Vue d\'ensemble du pipeline</a>'


def phase_modules() -> dict[str, str]:
    """Renvoie, par phase, le module qui la déclare (`PHASE`) parmi les modules importés par `pipeline.phases`."""
    return {
        m.PHASE.name: m.__name__
        for m in vars(pipeline_phases).values()
        if isinstance(m, ModuleType) and isinstance(getattr(m, "PHASE", None), Phase)
    }


def code_links() -> dict[str, str]:
    """Renvoie, par tâche, l'adresse de la référence du module qui déclare sa phase ; celle de `pipeline.phases` pour la tâche de l'orchestrateur."""
    modules = phase_modules()

    def href(module: str) -> str:
        return "../reference/" + module.replace(".", "/") + "/"

    return {
        t: href(modules[t.split(".", 1)[0]] if "." in t else pipeline_phases.__name__)
        for t in etapes.placed_tasks()
    }


def doc_href(doc: str) -> str:
    """Renvoie l'adresse d'un chapitre de `docs/pipeline` depuis la page publiée : `02-harvest.md#ancre` donne `02-harvest/#ancre`."""
    page, _, anchor = doc.partition("#")
    return page.removesuffix(".md") + "/" + (f"#{anchor}" if anchor else "")


def problems() -> list[str]:
    """Renvoie les tâches mal rangées (`etapes.placement_problems`), les tâches sans description et les phases sans module."""
    undescribed = [f"tâche sans description : {t}" for t in etapes.placed_tasks() if t not in SHORT]
    modules = phase_modules()
    orphans = [
        f"phase sans module : {p.name}" for p in pipeline_phases.PHASES if p.name not in modules
    ]
    return etapes.placement_problems() + undescribed + orphans


def fragment() -> str:
    """Renvoie le contenu de la page, sans squelette HTML."""
    data = {
        "nodes": etapes.NODES,
        "affluents": etapes.AFFLUENTS,
        "layout": etapes.LAYOUT,
        "edges": etapes.EDGES,
        "descriptions": {t: SHORT[t] for t in etapes.placed_tasks()},
        "docs": {k: doc_href(v) for k, v in etapes.doc_links().items()},
        "code": code_links(),
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
