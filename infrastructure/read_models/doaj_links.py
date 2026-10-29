"""Lien vers la fiche DOAJ d'une revue, à partir des données du dump DOAJ."""

from __future__ import annotations

from urllib.parse import urlparse

DOAJ_TOC_URL = "https://doaj.org/toc/{id}"
"""Modèle d'URL de la fiche d'une revue du DOAJ (table des matières)."""


def build_doaj_toc_url(doaj_id: str | None) -> str | None:
    """URL de la fiche DOAJ d'après un `DOAJ id`, ou `None` sans identifiant."""
    if not doaj_id:
        return None
    return DOAJ_TOC_URL.format(id=doaj_id)


DOAJ_HOST = urlparse(DOAJ_TOC_URL).netloc
"""Hôte des fiches DOAJ, dérivé de `DOAJ_TOC_URL`."""


def _est_une_fiche_doaj(url: str) -> bool:
    """Vrai si `url` désigne une page de `DOAJ_HOST` par le web.

    L'URL de fiche que le dump fournit toute faite alimente l'attribut `href` d'un lien. La confronter à l'hôte et au schéma attendus donne aux liens affichés une propriété uniforme : l'hôte de leur adresse est écrit dans le code.
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
