"""Adapter WoS pour la phase extract : HTTP (API Expanded) +
écritures staging + config.

Implémente le port `application.ports.pipeline.extract.wos.WosExtractAdapter`.
L'orchestration de la phase (boucle par année, pauses, breather) vit
côté `application.pipeline.extract.extract_wos`.
"""

from __future__ import annotations

import time
from typing import Any

import requests
from sqlalchemy import Connection

from application.ports.pipeline.extract._common import BatchInsertCounts
from application.ports.pipeline.extract.wos import WosExtractAdapter, WosExtractConfig
from infrastructure.sources.api_limits import WOS_DELAY, WOS_PER_PAGE
from infrastructure.sources.common import upsert_staging
from infrastructure.sources.config import (
    get_extraction_api_ids,
    get_years,
)
from infrastructure.sources.http_retry import http_request_with_retry
from infrastructure.sources.wos import parsing


class PgWosExtractAdapter(WosExtractAdapter):
    """Adapter PostgreSQL + HTTP pour `WosExtractAdapter`.

    Construit avec une `base_url` et une `api_key`. Les méthodes HTTP
    formatent les paramètres et délèguent à `http_request_with_retry`
    avec un backoff conservateur (`initial_backoff=2.0`) — WoS est plus
    sensible aux 429.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._url = base_url
        self._api_key = api_key
        self._headers = {"X-ApiKey": api_key, "Accept": "application/json"}
        self._last_request_at: float | None = None

    def _get(self, params: dict[str, Any], label: str) -> dict[str, Any]:
        """GET WoS Expanded, auto rate-limité : au moins `WOS_DELAY` entre deux appels.

        L'adapter se rate-limite seul, quel que soit l'appelant — l'orchestrateur
        n'ordonnance plus le délai de politesse (il garde en revanche ses pauses
        propres : breather périodique, backoff sur page vide, pause inter-années).
        On mesure l'écart depuis la dernière requête au lieu de dormir
        systématiquement après coup.
        """
        if self._last_request_at is not None:
            wait = WOS_DELAY - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        try:
            return http_request_with_retry(
                "GET",
                self._url,
                params=params,
                headers=self._headers,
                timeout=60,
                retry_on_empty_body=True,
                initial_backoff=2.0,
                label=label,
            )
        finally:
            self._last_request_at = time.monotonic()

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> WosExtractConfig:
        affiliations = get_extraction_api_ids(conn, "wos")
        return WosExtractConfig(
            base_url=self._url,
            affiliations=affiliations,
            has_api_key=bool(self._api_key),
        )

    def get_years(self, conn: Connection, *, start_year: int | None = None) -> list[int]:
        return get_years(conn, start_year=start_year)

    # ── Parsing & requête (pur, sans I/O) ──────────────────────

    def build_query(self, year: int, affiliations: list[str]) -> str:
        """Construit la requête WoS Advanced Search (cf. `parsing`)."""
        return parsing.build_query(year, affiliations)

    def get_records(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extrait la liste de records d'une réponse WoS (cf. `parsing`)."""
        return parsing.get_records(data)

    def get_records_found(self, data: dict[str, Any]) -> int:
        """Extrait le nombre total de records trouvés (cf. `parsing`)."""
        return parsing.get_records_found(data)

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, year: int, first_record: int, affiliations: list[str]) -> dict[str, Any]:
        """Récupère une page de résultats via une recherche complète.

        Note : la pagination via queryId ne fonctionne pas de façon fiable
        (réponses vides), on refait une recherche avec firstRecord à chaque page.
        """
        params = {
            "databaseId": "WOS",
            "usrQuery": parsing.build_query(year, affiliations),
            "count": WOS_PER_PAGE,
            "firstRecord": first_record,
        }
        return self._get(params, label=f"({year}, rec {first_record})")

    def check_quota(self) -> str | None:
        """Probe l'API pour récupérer le header `X-REC-AmtPerYear-Remaining`."""
        resp = requests.get(
            self._url,
            headers=self._headers,
            params={
                "databaseId": "WOS",
                "usrQuery": "OG=(test)",
                "count": "0",
                "firstRecord": "1",
            },
            timeout=30,
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"Erreur d'authentification WoS ({resp.status_code}). "
                f"Vérifier la clé API. Réponse : {resp.text[:300]}"
            )
        if resp.status_code != 200:
            return None
        return resp.headers.get("X-REC-AmtPerYear-Remaining")

    # ── SQL ────────────────────────────────────────────────────

    def insert_batch(self, conn: Connection, records: list[dict[str, Any]]) -> BatchInsertCounts:
        """UPSERT bulk d'un batch de records WoS, ventilé new/updated via `xmax`.

        Le caller est responsable du `conn.commit()` après cette méthode.
        """
        new_count = 0
        updated_count = 0
        unchanged_count = 0
        for rec in records:
            inserted, changed = upsert_staging(
                conn,
                source="wos",
                source_id=parsing.extract_ut(rec),
                doi=parsing.extract_doi(rec),
                raw_data=rec,
            )
            if inserted:
                new_count += 1
            elif changed:
                updated_count += 1
            else:
                unchanged_count += 1
        return BatchInsertCounts(new=new_count, updated=updated_count, unchanged=unchanged_count)
