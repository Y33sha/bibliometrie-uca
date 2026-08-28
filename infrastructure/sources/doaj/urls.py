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


WEB_SCHEMES = ("http://", "https://")
"""Schémas d'URL qu'un lien affiché peut porter. Une URL reçue d'une source alimente l'attribut `href` d'un lien : un schéma `javascript:` ou `data:` y donnerait un lien qui s'exécute au clic, l'interface ne validant pas les schémas pour son compte."""


def resolve_doaj_url(payload_url: str | None, doaj_id: str | None) -> str | None:
    """URL de fiche DOAJ à partir d'un payload, quelle que soit sa provenance.

    Privilégie l'URL toute faite (`'URL in DOAJ'` du dump CSV) et la reconstruit depuis le `'DOAJ id'` à défaut. `None` si ni l'un ni l'autre.

    L'URL du payload est retenue à condition d'être une adresse web (`WEB_SCHEMES`) : c'est la seule URL du projet dont le schéma vienne de l'extérieur, les autres liens affichés étant composés sur un hôte écrit dans le code. Un schéma d'une autre nature vaut absence, et la reconstruction depuis l'identifiant prend le relais.
    """
    if payload_url and payload_url.lower().startswith(WEB_SCHEMES):
        return payload_url
    return build_doaj_toc_url(doaj_id)
