"""Adapter theses.fr pour la phase extract : HTTP (recherche paginée
par `debut`/`nombre`) + écritures staging + config.

Implémente le port
`application.ports.pipeline.extract.theses.ThesesExtractAdapter`.
L'orchestration de la phase (boucle par PPN × statut, filtre année
post-fetch) vit côté `application.pipeline.extract.extract_theses`.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Connection

from application.ports.pipeline.extract.theses import (
    ThesesExtractAdapter,
    ThesesExtractConfig,
)
from infrastructure.sources.api_limits import THESES_DELAY, THESES_PER_PAGE
from infrastructure.sources.common import upsert_staging
from infrastructure.sources.config import get_extraction_api_ids
from infrastructure.sources.http_retry import http_request_with_retry


def extract_doi(these: dict[str, Any]) -> str | None:
    """Extrait le DOI d'une thèse s'il est présent et non vide, sinon `None`."""
    doi = these.get("doi")
    if doi and isinstance(doi, str) and doi.strip():
        return doi.strip()
    return None


class PgThesesExtractAdapter(ThesesExtractAdapter):
    """Adapter PostgreSQL + HTTP pour `ThesesExtractAdapter`.

    Construit avec une `base_url` (endpoint `/api/v1/theses/recherche/`).
    """

    def __init__(self, base_url: str) -> None:
        self._url = base_url
        self._last_request_at: float | None = None

    def _get(self, params: dict[str, Any], label: str) -> dict[str, Any]:
        """GET theses.fr, auto rate-limité : au moins `THESES_DELAY` entre deux appels.

        L'adapter se rate-limite seul, quel que soit l'appelant — l'orchestrateur
        n'ordonnance aucun `sleep`. On mesure l'écart depuis la dernière requête au
        lieu de dormir systématiquement après coup : le temps de traitement entre
        deux pages (upserts, commit) est déjà décompté du délai.
        """
        if self._last_request_at is not None:
            wait = THESES_DELAY - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        try:
            return http_request_with_retry("GET", self._url, params=params, timeout=30, label=label)
        finally:
            self._last_request_at = time.monotonic()

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> ThesesExtractConfig:
        ppns = get_extraction_api_ids(conn, "theses")
        return ThesesExtractConfig(base_url=self._url, ppns=ppns)

    # ── Parsing & requête (pur, sans I/O) ──────────────────────

    def build_query(self, ppn: str) -> str:
        """Construit la chaîne de recherche theses.fr (filtre par PPN d'établissement)."""
        return f"etabSoutenancePpn:({ppn})"

    def per_page(self) -> int:
        """Taille de page theses.fr (max accepté par l'API ; cf. `api_limits`)."""
        return THESES_PER_PAGE

    def extract_id(self, these: dict[str, Any]) -> str:
        """Extrait l'identifiant unique d'une thèse (champ `id`).

        Pour les thèses soutenues, c'est le NNT (ex: `2021UCFAC022`) ; pour les
        thèses en cours, c'est un id theses.fr (ex: `s367812`). Les deux vivent
        dans la même colonne `id` de l'API recherche.
        """
        return these.get("id", "")

    def extract_doi(self, these: dict[str, Any]) -> str | None:
        """Extrait le DOI s'il est présent et non vide, sinon `None`."""
        return extract_doi(these)

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, query: str, *, debut: int, nombre: int) -> dict[str, Any]:
        """Récupère une page de résultats depuis l'API theses.fr."""
        params = {
            "q": query,
            "debut": debut,
            "nombre": nombre,
        }
        return self._get(params, label=f"theses debut={debut}")

    # ── SQL ────────────────────────────────────────────────────

    def upsert_these(self, conn: Connection, these: dict[str, Any]) -> tuple[bool, bool, bool]:
        """UPSERT staging via le helper canonique, ventilé `(new, updated, unchanged)`.

        Exactement un `True` : `updated` = contenu réécrit (hash changé),
        `unchanged` = re-vu identique.
        """
        inserted, changed = upsert_staging(
            conn,
            source="theses",
            source_id=self.extract_id(these),
            doi=self.extract_doi(these),
            raw_data=these,
        )
        if inserted:
            return (True, False, False)
        return (False, changed, not changed)
