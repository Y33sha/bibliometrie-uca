"""Adapter DataCite pour ``application.pipeline.extract.fetch_missing_doi``.

DataCite est ingérée DOI-driven : pour les DOI présents dans une autre source
mais absents du staging DataCite, on interroge l'endpoint ``GET /dois`` en
**batch** via ``query=doi:"a" OR doi:"b" …`` (réponse JSON:API, liste de nœuds
``data``) et on insère chaque nœud (id + ``attributes`` + ``relationships``)
dans ``staging`` avec ``source='datacite'``.

Batch de ``batch_size`` DOI par requête : la latence DataCite a une falaise nette
au-delà d'une dizaine de clauses ``OR`` (mesuré : ~0,3 s à 10 DOI, ~2,6 s à 20),
donc on reste à 10 — coût par DOI minimal, et c'est alors le rate-limit qui borne.
Les DOI absents de la réponse d'un batch sont les introuvables (cf. ci-dessous).

Le pool de DOI candidats est filtré en amont par ``get_cross_import_dois`` :
seuls les DOI dont le préfixe résout à la RA ``DataCite`` (ou pas encore résolu)
sont soumis, ce qui évite les 404 systématiques sur les DOI Crossref.

Les DOI introuvables (absents de la réponse du batch) sont stockés avec
``not_found_at`` et ``processed=TRUE`` pour ne pas être réinterrogés à chaque
run. DataCite est la source native du DOI pour ses préfixes : un miss est
définitif (DOI erroné ou non DataCite), donc le stub reste dans ``staging``
(pas de backoff).
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from infrastructure.sources.common import compute_hash
from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email
from infrastructure.sources.http_retry_async import http_request_with_retry_async

_USER_AGENT_TEMPLATE = "BibliometrieUCA-pipeline/1.0 (mailto:{email})"


def _record_doi(record: dict) -> str | None:
    """DOI canonique (lowercase) d'un nœud JSON:API `data` : `attributes.doi`,
    sinon `id` (les deux portent le DOI). `None` si aucun des deux n'est présent."""
    attributes = record.get("attributes")
    doi_raw = ""
    if isinstance(attributes, dict):
        doi_raw = attributes.get("doi") or ""
    doi_raw = doi_raw or record.get("id") or ""
    return doi_raw.lower() or None


_INSERT_NOT_FOUND_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, not_found_at, processed)
    VALUES ('datacite', :doi, :doi, '{}'::jsonb, now(), TRUE)
    ON CONFLICT (source, source_id) DO NOTHING
    """
)

_INSERT_DATACITE_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES ('datacite', :doi, :doi, :raw_data, :raw_hash, FALSE)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.raw_data ELSE staging.raw_data END,
        raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE ELSE staging.processed END,
        last_seen_at = now()
    """
).bindparams(bindparam("raw_data", type_=JSONB))


class DataciteFetchMissingDoiAdapter:
    """Adapter async conforme au ``AsyncFetchMissingDoiAdapter`` Protocol."""

    source_key = "datacite"
    batch_size = 10
    # Limites DataCite par tier (fenêtre glissante de 5 min, par IP) : 3000
    # (authentifié), 1000 (identifié = User-Agent avec mailto, notre cas), 500
    # (anonyme). On est identifié → 1000 / 5 min ≈ 3,3 req/s. On vise pile cette
    # limite, sans marge (3 concurrentes × pause 0,9 s ≈ 3,3 req/s) : un 429 + coupe-
    # circuit ponctuel en fin de fenêtre est rattrapé au run suivant (pool convergent).
    # Chaque requête rapatriant 10 DOI, le débit utile est ~10× (≈ 33 DOI/s).
    max_concurrent = 3
    request_delay_s = 0.9

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls()["datacite"]
        email = get_polite_pool_email(conn)
        self.headers = {
            "User-Agent": _USER_AGENT_TEMPLATE.format(email=email),
            "Accept": "application/vnd.api+json",
        }

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        # Batch : `query=doi:"a" OR doi:"b" …`. Le champ `doi` est requêté en
        # phrase exacte ; on remappe ensuite les nœuds reçus aux DOI demandés par
        # comparaison stricte (lowercase), sans se fier à l'ordre ni au volume.
        clause = " OR ".join(f'doi:"{d}"' for d in dois)
        url = f"{self.base_url}/dois"
        try:
            data = await http_request_with_retry_async(
                client,
                "GET",
                url,
                params={"query": clause, "page[size]": len(dois)},
                headers=self.headers,
                timeout=30,
                label=f"{len(dois)} DOI",
            )
        except (httpx.HTTPStatusError, httpx.RequestError):
            # Échec du batch entier : rien remonté, les DOI restent hors staging
            # et seront retentés au prochain run (pool convergent).
            return []

        records = data.get("data")
        if not isinstance(records, list):
            return []

        # DOI demandés non retournés = confirmés absents de DataCite (source
        # native du DOI pour ses préfixes) : miss définitif, stub `staging`.
        found: dict[str, dict] = {}
        for rec in records:
            if isinstance(rec, dict):
                doi = _record_doi(rec)
                if doi:
                    found[doi] = rec
        out: list[dict] = list(found.values())
        out.extend(not_found_marker(d) for d in dois if d.lower() not in found)
        return out

    def insert(self, conn: Connection, record: dict) -> bool:
        if is_not_found_marker(record):
            conn.execute(_INSERT_NOT_FOUND_SQL, {"doi": record["_doi"]})
            conn.commit()
            return False

        # `record` est le nœud JSON:API `data` : son `id` est le DOI, dupliqué
        # dans `attributes.doi`, normalisé en lowercase comme les autres sources.
        doi = _record_doi(record)
        if not doi:
            return False

        result = conn.execute(
            _INSERT_DATACITE_SQL,
            {"doi": doi, "raw_data": record, "raw_hash": compute_hash(record)},
        )
        conn.commit()
        return result.rowcount > 0
