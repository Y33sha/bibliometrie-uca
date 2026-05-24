"""Constantes et helpers purs pour l'extraction theses.fr.

Tout ce qui peut être consommé par l'orchestrateur applicatif sans toucher à `infrastructure` : timing de rate-limit, taille de page, construction de requête `q=...`, parsing des thèses.
"""

from __future__ import annotations

from typing import Any

# ── Rate-limit / pagination ────────────────────────────────────────

THESES_DELAY = 0.3
"""Pause entre deux requêtes consécutives à theses.fr (s)."""

THESES_PER_PAGE = 500
"""Taille de page (max accepté par l'API)."""


# ── Requête ───────────────────────────────────────────────────────


def build_query(ppn: str) -> str:
    """Construit la chaîne de recherche pour l'API theses.fr (filtre par PPN d'établissement)."""
    return f"etabSoutenancePpn:({ppn})"


# ── Parsing de documents ───────────────────────────────────────────


def extract_theses_id(these: dict[str, Any]) -> str:
    """Extrait l'identifiant unique d'une thèse (champ `id`).

    Pour les thèses soutenues, c'est le NNT (ex: `2021UCFAC022`) ; pour les thèses en cours, c'est un id theses.fr (ex: `s367812`). Les deux vivent dans la même colonne `id` de l'API recherche.
    """
    return these.get("id", "")


def extract_doi(these: dict[str, Any]) -> str | None:
    """Extrait le DOI s'il est présent et non vide, sinon `None`."""
    doi = these.get("doi")
    if doi and isinstance(doi, str) and doi.strip():
        return doi.strip()
    return None
