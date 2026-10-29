# STATUS: maintenance
"""Pays des éditeurs, d'après OpenAlex Publishers.

Hors pipeline, lancé à la demande. Seuls les éditeurs sans pays reçoivent celui d'OpenAlex : une valeur saisie par un administrateur est préservée, et deux exécutions successives donnent le même résultat.

Le circuit-breaker de source arrête la boucle quand OpenAlex est à bout de budget (429). Le reste est repris à l'exécution suivante.

Usage :
    python -m interfaces.cli.maintenance.enrich_publishers [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import os
from collections import Counter
from collections.abc import Callable
from typing import NamedTuple, NotRequired, TypedDict, cast

import httpx2
from sqlalchemy import Connection, text

from domain.types import as_mapping
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.savepoint import rollback_unless_invalidated
from infrastructure.observability.log import setup_logger
from pipeline.http.circuit_breaker import SourceUnavailableError, source_tripped
from pipeline.http.http_retry import http_request_with_retry
from pipeline.ingestion.api_params import API_BASE_URLS, request_budget
from pipeline.ingestion.credentials import source_credentials_missing
from pipeline.ingestion.openalex.api import credential_params
from pipeline.ingestion.openalex.payload import full_openalex_id, short_openalex_id
from pipeline.runtime.access_source import access_source
from pipeline.runtime.observability.metrics import PhaseMetrics

log = setup_logger("enrich_publishers", os.path.dirname(__file__))

BATCH_SIZE = 50

_COUNTRYLESS = text("""
    SELECT id, openalex_id FROM publishers
    WHERE openalex_id IS NOT NULL AND country IS NULL
    ORDER BY id
    LIMIT :limit
""")

_SET_COUNTRY = text("UPDATE publishers SET country = :country WHERE id = :id AND country IS NULL")

FetchPublishersBatch = Callable[[list[str]], dict[str, str | None]]
"""Requête injectée : pays de chaque éditeur, par identifiant OpenAlex court ; `None` quand OpenAlex n'en donne pas. Un éditeur sans réponse est absent du dictionnaire."""


def find_countryless(conn: Connection, limit: int | None = None) -> list[tuple[int, str]]:
    """Éditeurs sans pays qui ont un `openalex_id`, par id ; tous sans `limit`."""
    return [(r.id, r.openalex_id) for r in conn.execute(_COUNTRYLESS, {"limit": limit}).all()]


class _OpenAlexPublisher(TypedDict):
    """Partie du payload d'OpenAlex Publishers lue ici."""

    id: str
    country_codes: NotRequired[list[str]]


def extract_country(source: _OpenAlexPublisher) -> str | None:
    """Pays d'un éditeur dans le payload d'OpenAlex Publishers : le premier code de `country_codes`, en minuscules, en général celui du siège ; `None` sans code."""
    country_codes = source.get("country_codes") or []
    return country_codes[0].lower() if country_codes else None


def fetch_publishers_batch(
    openalex_ids: list[str], *, openalex_publishers_api: str
) -> dict[str, str | None]:
    """Interroge OpenAlex Publishers pour un lot d'identifiants (filtre à `|`, 50 au plus).

    Renvoie `{}` si OpenAlex refuse le lot (4xx) ou reste indisponible après les nouvelles tentatives ; la boucle consulte l'état du circuit-breaker.
    """
    params: dict[str, str] = {
        "filter": f"ids.openalex:{'|'.join(full_openalex_id(oid) for oid in openalex_ids)}",
        "per_page": str(len(openalex_ids)),
        "select": "id,country_codes",
        **credential_params(),
    }
    try:
        data = as_mapping(
            http_request_with_retry(
                "GET", openalex_publishers_api, params=params, timeout=30, label="publishers batch"
            )
        )
    except (httpx2.HTTPStatusError, SourceUnavailableError) as exc:
        log.warning("OpenAlex publishers batch : %r", exc)
        return {}
    results = cast("list[_OpenAlexPublisher]", data.get("results", []))
    return {short_openalex_id(source["id"]): extract_country(source) for source in results}


class _BatchOutcome(NamedTuple):
    """Compteurs du traitement d'un lot d'éditeurs."""

    updated: int
    no_response: int
    countries: Counter[str]


def _enrich_batch(
    conn: Connection,
    id_map: dict[str, int],
    countries_by_id: dict[str, str | None],
    *,
    dry_run: bool,
) -> _BatchOutcome:
    """Écrit le pays OpenAlex des éditeurs d'un lot. `id_map` associe `openalex_id` et id de l'éditeur."""
    updated = no_response = 0
    countries: Counter[str] = Counter()
    for oa_id, publisher_id in id_map.items():
        if oa_id not in countries_by_id:
            no_response += 1
            continue
        country = countries_by_id[oa_id]
        if not country:
            continue
        if (
            not dry_run
            and not conn.execute(_SET_COUNTRY, {"id": publisher_id, "country": country}).rowcount
        ):
            continue
        countries[country] += 1
        updated += 1
    return _BatchOutcome(updated, no_response, countries)


def run_enrich_publishers_from_openalex(
    conn: Connection,
    logger: logging.Logger,
    *,
    fetch_batch: FetchPublishersBatch,
    limit: int = 0,
    dry_run: bool = False,
) -> None:
    """Pose le pays OpenAlex des éditeurs qui n'en ont pas, par lots de `BATCH_SIZE`, avec un commit par lot."""
    try:
        publishers = find_countryless(conn, limit or None)
        total = len(publishers)
        logger.info("%s éditeurs à enrichir (avec openalex_id, sans pays).", total)
        if total == 0:
            return

        updated = no_response = processed = 0
        country_counter: Counter[str] = Counter()
        for i in range(0, total, BATCH_SIZE):
            if source_tripped():
                if not dry_run:
                    conn.commit()
                logger.warning(
                    "⚡ Coupe-circuit OpenAlex : enrichissement éditeurs interrompu à %d/%d. "
                    "Reste retenté à la prochaine exécution.",
                    processed,
                    total,
                )
                return
            id_map = {oa_id: publisher_id for publisher_id, oa_id in publishers[i : i + BATCH_SIZE]}
            countries_by_id = fetch_batch(list(id_map))
            outcome = _enrich_batch(conn, id_map, countries_by_id, dry_run=dry_run)
            updated += outcome.updated
            no_response += outcome.no_response
            country_counter += outcome.countries
            processed += len(id_map)
            if not dry_run:
                conn.commit()
            logger.info("  %s/%s — %s pays écrits", min(i + BATCH_SIZE, total), total, updated)

        logger.info(
            "Terminé : %s/%s éditeurs mis à jour, %s sans réponse.", updated, total, no_response
        )
        if country_counter:
            distrib = ", ".join(f"{c}={n}" for c, n in country_counter.most_common(10))
            logger.info("Pays les plus posés : %s", distrib)
    except KeyboardInterrupt:
        # Un Ctrl+C en plein `execute` avorte la transaction : le lot en cours est annulé, les lots déjà commités restent.
        rollback_unless_invalidated(conn)
        logger.warning("Interruption — lots déjà committés conservés.")
        raise
    except Exception as e:
        rollback_unless_invalidated(conn)
        logger.error("Erreur fatale : %s", e)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limiter le nombre d'éditeurs traités (0 = tous les candidats).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Aperçu sans modifier la base.")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    publishers_api = API_BASE_URLS["openalex_publishers"]

    def enrich() -> PhaseMetrics:
        run_enrich_publishers_from_openalex(
            conn,
            log,
            fetch_batch=lambda oa_ids: fetch_publishers_batch(
                oa_ids, openalex_publishers_api=publishers_api
            ),
            limit=args.limit,
            dry_run=args.dry_run,
        )
        return PhaseMetrics()

    try:
        # Trois lots consécutifs à bout de budget (429) signalent un quota OpenAlex du jour épuisé : le reste attend l'exécution suivante.
        access_source(
            "openalex",
            enrich,
            phase="enrich_publishers",
            logger=log,
            credentials_missing=source_credentials_missing,
            request_budget=request_budget,
            threshold=3,
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
