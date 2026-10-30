"""Lien vers la fiche DOAJ d'une revue, à partir des données du dump DOAJ."""

from __future__ import annotations

from urllib.parse import urlparse

DOAJ_TOC_URL = "https://doaj.org/toc/{id}"
"""Modèle d'URL de la fiche d'une revue du DOAJ (table des matières)."""


def build_doaj_toc_url(doaj_id: str | None) -> str | None:
    """Renvoie l'URL de la fiche DOAJ d'après un `DOAJ id`, ou `None` sans identifiant."""
    if not doaj_id:
        return None
    return DOAJ_TOC_URL.format(id=doaj_id)


DOAJ_HOST = urlparse(DOAJ_TOC_URL).netloc
"""Hôte des fiches DOAJ, dérivé de `DOAJ_TOC_URL`."""


def _est_une_fiche_doaj(url: str) -> bool:
    """Vrai si `url` désigne une page de `DOAJ_HOST` par le web.

    Le dump fournit une URL de fiche toute faite, utilisée comme attribut `href` d'un lien. Le contrôle de l'hôte et du schéma garantit que l'hôte de chaque lien affiché est écrit dans le code.
    """
    adresse = urlparse(url)
    return adresse.scheme in ("http", "https") and adresse.netloc.lower() == DOAJ_HOST


def resolve_doaj_url(payload_url: str | None, doaj_id: str | None) -> str | None:
    """Renvoie l'URL de fiche DOAJ d'un payload, quelle que soit sa provenance, ou `None`.

    L'URL toute faite (`'URL in DOAJ'` du dump CSV) est retenue si elle désigne une fiche DOAJ. À défaut, l'URL est reconstruite depuis le `'DOAJ id'`.
    """
    if payload_url and _est_une_fiche_doaj(payload_url):
        return payload_url
    return build_doaj_toc_url(doaj_id)
