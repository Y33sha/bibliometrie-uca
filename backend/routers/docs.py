"""Documentation router — sert les fichiers .md depuis docs/."""

import os
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter()

DOCS_DIR = Path(__file__).parent.parent.parent / "docs"

# Pages de doc et leur titre pour la sidebar (dans l'ordre d'affichage)
DOC_PAGES = [
    {"slug": "architecture", "title": "Architecture des données"},
    {"slug": "sources", "title": "Sources de données"},
    {"slug": "pipeline", "title": "Pipeline de traitement"},
    {"slug": "exploitation", "title": "Guide d'exploitation"},
    {"slug": "guide-utilisateur", "title": "Guide utilisateur"},
    {"slug": "glossaire", "title": "Glossaire"},
]


@router.get("/api/docs")
async def list_docs():
    """Liste les pages de documentation disponibles."""
    return DOC_PAGES


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

    return {"slug": slug, "title": title, "content": content}
