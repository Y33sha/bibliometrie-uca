# STATUS: maintenance
"""Enrichissement (cosmétique) du `country` des éditeurs depuis OpenAlex Publishers.

Hors pipeline (champs d'affichage), lancé à la demande. Politique « NULL only » : les valeurs saisies par un administrateur sont préservées ; idempotent.

Usage :
    python -m interfaces.cli.maintenance.enrich_publishers [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from application.ports.pipeline.circuit_breaker import SourceUnavailableError
from application.services.publishers.enrich_country import run_enrich_publishers_from_openalex
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import publisher_repository
from infrastructure.sources.api_params import API_BASE_URLS, OPENALEX_DELAY
from infrastructure.sources.circuit_breaker import (
    SourceCircuitBreaker,
    reset_current_breaker,
    set_current_breaker,
)
from infrastructure.sources.config import (
    get_openalex_api_key,
    get_polite_pool_email,
)
from infrastructure.sources.openalex.publisher_enrichment import fetch_publishers_batch

log = setup_logger("enrich_publishers", os.path.dirname(__file__))


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
    # Seuil 3 : trois lots consécutifs à bout de budget (429) suffisent à conclure que le
    # quota OpenAlex du jour est épuisé et à reporter le reste à la prochaine exécution.
    breaker = SourceCircuitBreaker("openalex publishers", threshold=3)
    token = set_current_breaker(breaker)
    api_key = get_openalex_api_key()
    mailto = get_polite_pool_email()
    publishers_api = API_BASE_URLS["openalex_publishers"]
    try:
        run_enrich_publishers_from_openalex(
            conn,
            log,
            publisher_repo=publisher_repository(conn),
            fetch_batch=lambda oa_ids: fetch_publishers_batch(
                oa_ids,
                openalex_publishers_api=publishers_api,
                api_key=api_key,
                mailto=mailto,
            ),
            breaker=breaker,
            limit=args.limit,
            dry_run=args.dry_run,
            rate_delay=OPENALEX_DELAY,
        )
    except SourceUnavailableError:
        log.warning("OpenAlex indisponible : enrichissement abandonné, à relancer plus tard.")
    finally:
        reset_current_breaker(token)
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
