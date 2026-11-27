"""Page du déroulement du pipeline : chaque tâche rangée une fois et décrite, liens vers la documentation valides, page de la documentation à jour."""

import re
from pathlib import Path

from pymdownx.slugs import slugify

from interfaces.cli.dev.deroulement import etapes
from interfaces.cli.dev.deroulement.page import DOC_PAGE, DOCS_DIR, document, problems

_SLUG = slugify(case="lower")
"""Ancres des intertitres, comme `zensical.toml` les calcule (`toc.slugify`)."""


def _anchors(page: Path) -> set[str]:
    headings = re.findall(r"^#{1,6} (.+)$", page.read_text(), flags=re.MULTILINE)
    return {_SLUG(h.replace("`", ""), "-") for h in headings}


def test_chaque_tache_est_rangee_une_fois_et_decrite():
    assert problems() == []


def test_chaque_lien_vers_la_documentation_designe_un_chapitre_et_un_intertitre():
    broken = []
    for element, doc in etapes.doc_links().items():
        name, _, anchor = doc.partition("#")
        page = DOCS_DIR / name
        if not page.exists() or (anchor and anchor not in _anchors(page)):
            broken.append(f"{element} : {doc}")
    assert broken == []


def test_la_page_de_la_documentation_est_a_jour():
    assert DOC_PAGE.read_text() == document(), "uv run python -m interfaces.cli.dev.deroulement"
