"""Enrichissement (cosmétique) des éditeurs : pays, ROR, type d'éditeur.

Hors pipeline (ces champs sont purement d'affichage) : lancé à la demande. Enchaîne
les trois sources dans l'ordre, sur la même connexion :

1. OpenAlex Publishers → `country` + `ror` (si NULL) ;
2. Crossref Members → `country` (fallback pour ceux sans pays après OpenAlex,
   reliés à un membre Crossref via `doi_prefixes`) ;
3. ROR → `publisher_type` (depuis le `ror` posé en 1).

Politique d'écrasement « NULL/unknown only » : ne touche jamais une valeur saisie
par un administrateur. Idempotent : chaque étape ne re-sélectionne que les éditeurs
au champ encore manquant.

Usage :
    python -m interfaces.cli.maintenance.enrich_publishers [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from application.publishers_enrichment import (
    CrossrefMemberFetcher,
    RorFetcher,
    run_enrich_publishers_from_crossref_members,
    run_enrich_publishers_from_openalex,
    run_enrich_publishers_from_ror,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.publishers_enrichment import PgPublisherEnrichmentQueries
from infrastructure.repositories import publisher_repository
from infrastructure.sources.api_limits import DOAJ_DELAY
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)
from infrastructure.sources.crossref.members import fetch_crossref_member
from infrastructure.sources.doi_prefixes.clients import build_user_agent
from infrastructure.sources.ror import build_ror_user_agent, fetch_ror_record

log = setup_logger("enrich_publishers", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limiter le nombre d'éditeurs traités par étape (0 = tous les candidats).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Aperçu sans modifier la base.")
    args = parser.parse_args()

    queries = PgPublisherEnrichmentQueries()
    api_base_urls = get_api_base_urls()
    conn = get_sync_engine().connect()
    try:
        repo = publisher_repository(conn)
        mailto = get_polite_pool_email(conn)

        log.info("▶ OpenAlex Publishers (country + ror)")
        run_enrich_publishers_from_openalex(
            conn,
            queries,
            log,
            publisher_repo=repo,
            api_key=get_openalex_api_key(conn),
            mailto=mailto,
            openalex_publishers_api=api_base_urls["openalex_publishers"],
            limit=args.limit,
            dry_run=args.dry_run,
            rate_delay=DOAJ_DELAY,
        )

        log.info("▶ Crossref Members (fallback country)")
        crossref_user_agent = build_user_agent(mailto)
        crossref_fetcher: CrossrefMemberFetcher = lambda member_id: fetch_crossref_member(  # noqa: E731
            member_id, user_agent=crossref_user_agent, logger=log
        )
        run_enrich_publishers_from_crossref_members(
            conn,
            queries,
            log,
            publisher_repo=repo,
            fetcher=crossref_fetcher,
            limit=args.limit,
            dry_run=args.dry_run,
        )

        log.info("▶ ROR (publisher_type)")
        ror_base_url = api_base_urls["ror"]
        ror_user_agent = build_ror_user_agent(mailto)
        ror_fetcher: RorFetcher = lambda ror: fetch_ror_record(  # noqa: E731
            ror, base_url=ror_base_url, user_agent=ror_user_agent, logger=log
        )
        run_enrich_publishers_from_ror(
            conn,
            queries,
            log,
            publisher_repo=repo,
            fetcher=ror_fetcher,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
