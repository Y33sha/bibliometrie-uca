"""Composition des URL de fiche DOAJ, à partir de ce qu'un payload en porte.

Purement textuel : ce module manipule des chaînes et rien d'autre. Le téléchargement du dump DOAJ vit à côté, dans `client.py`.
"""

from __future__ import annotations

from urllib.parse import urlparse

DOAJ_TOC_URL = "https://doaj.org/toc/{id}"
"""URL canonique d'une fiche journal DOAJ (table des matières)."""


def build_doaj_toc_url(doaj_id: str | None) -> str | None:
    """Reconstruit l'URL de la fiche DOAJ à partir d'un `DOAJ id`.

    Retourne `None` si l'id est absent — cas d'un payload sans `DOAJ id` (le dump CSV stocke l'URL toute faite sous `URL in DOAJ`).
    """
    if not doaj_id:
        return None
    return DOAJ_TOC_URL.format(id=doaj_id)


DOAJ_HOST = urlparse(DOAJ_TOC_URL).netloc
"""Hôte des fiches DOAJ, dérivé de l'URL canonique : une seule valeur à tenir à jour."""


def _est_une_fiche_doaj(url: str) -> bool:
    """Vrai si `url` désigne une page de `DOAJ_HOST` par le web.

    L'URL de fiche que le dump fournit toute faite alimente l'attribut `href` d'un lien. La confronter à l'hôte et au schéma attendus donne aux liens affichés une propriété uniforme : leur adresse porte un hôte écrit dans le code.
    """
    adresse = urlparse(url)
    return adresse.scheme in ("http", "https") and adresse.netloc.lower() == DOAJ_HOST


def resolve_doaj_url(payload_url: str | None, doaj_id: str | None) -> str | None:
    """URL de fiche DOAJ à partir d'un payload, quelle que soit sa provenance.

    Privilégie l'URL toute faite (`'URL in DOAJ'` du dump CSV), à condition qu'elle désigne une fiche DOAJ, et la reconstruit depuis le `'DOAJ id'` à défaut. `None` si ni l'un ni l'autre.
    """
    if payload_url and _est_une_fiche_doaj(payload_url):
        return payload_url
    return build_doaj_toc_url(doaj_id)
