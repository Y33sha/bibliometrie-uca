"""Documentation router — sert les fichiers .md depuis docs/."""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"

# Pages de doc et leur titre pour la sidebar (dans l'ordre d'affichage)
DOC_PAGES = [
    {"slug": "architecture", "title": "Architecture données"},
    {"slug": "sources", "title": "Sources de données"},
    {"slug": "pipeline", "title": "Pipeline de traitement"},
    {"slug": "exploitation", "title": "Guide d'exploitation"},
    {"slug": "guide-utilisateur", "title": "Guide utilisateur"},
    {"slug": "glossaire", "title": "Glossaire métier"},
]


@router.get("/api/docs")
async def list_docs():
    """Liste les pages de documentation disponibles."""
    return DOC_PAGES


@router.get("/api/docs/todos/all")
async def list_all_todos():
    """Collecte tous les <!-- TODO: ... --> de tous les fichiers .md."""
    todos = []
    todo_re = re.compile(r"<!--\s*TODO\s*:\s*(.+?)\s*-->")

    for page in DOC_PAGES:
        path = DOCS_DIR / f"{page['slug']}.md"
        if not path.exists():
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in todo_re.finditer(line):
                todos.append(
                    {
                        "page": page["slug"],
                        "page_title": page["title"],
                        "line": i,
                        "text": match.group(1).strip(),
                    }
                )

    return todos


@router.get("/api/docs/{slug}")
async def get_doc(slug: str):
    """Retourne le contenu markdown d'une page de documentation."""
    # Sécurité : pas de traversal
    if "/" in slug or "\\" in slug or ".." in slug:
        raise HTTPException(status_code=400, detail="Slug invalide")

    path = DOCS_DIR / f"{slug}.md"
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Document '{slug}' introuvable")

    content = path.read_text(encoding="utf-8")

    # Trouver le titre dans DOC_PAGES
    title = slug
    for page in DOC_PAGES:
        if page["slug"] == slug:
            title = page["title"]
            break

    # Extraire les titres h2/h3 pour la table des matières
    import re

    headings = []
    for line in content.splitlines():
        m = re.match(r"^(#{2})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            # Générer l'ancre comme le fait marked (lowercase, espaces → tirets, suppression ponctuation)
            anchor = re.sub(r"[^\w\s-]", "", text.lower())
            anchor = re.sub(r"[\s]+", "-", anchor).strip("-")
            headings.append({"level": level, "text": text, "anchor": anchor})

    return {"slug": slug, "title": title, "content": content, "headings": headings}
