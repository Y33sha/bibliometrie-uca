"""Composition des URL de fiche DOAJ, à partir de ce qu'un payload en porte.

Purement textuel : ce module manipule des chaînes et rien d'autre. Le téléchargement du dump DOAJ vit à côté, dans `client.py`.
"""

from __future__ import annotations

DOAJ_TOC_URL = "https://doaj.org/toc/{id}"
"""URL canonique d'une fiche journal DOAJ (table des matières)."""


def build_doaj_toc_url(doaj_id: str | None) -> str | None:
    """Reconstruit l'URL de la fiche DOAJ à partir d'un `DOAJ id`.

    Retourne `None` si l'id est absent — cas d'un payload sans `DOAJ id` (le dump CSV stocke l'URL toute faite sous `URL in DOAJ`).
    """
    if not doaj_id:
        return None
    return DOAJ_TOC_URL.format(id=doaj_id)


def resolve_doaj_url(payload_url: str | None, doaj_id: str | None) -> str | None:
    """URL de fiche DOAJ à partir d'un payload, quelle que soit sa provenance.

    Privilégie l'URL toute faite (`'URL in DOAJ'` du dump CSV) et la reconstruit depuis le `'DOAJ id'` à défaut. `None` si ni l'un ni l'autre.
    """
    return payload_url or build_doaj_toc_url(doaj_id)
