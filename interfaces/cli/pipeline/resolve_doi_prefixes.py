"""Point d'entrée CLI : résolution des préfixes DOI → RA + éditeur."""

import argparse
import os

from application.pipeline.resolve_doi_prefixes import run_resolve_doi_prefixes
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import doi_prefix_repository, publisher_repository
from infrastructure.sources.config import get_openalex_email
from infrastructure.sources.doi_prefixes.clients import (
    build_user_agent,
    fetch_crossref_prefix,
    resolve_ra,
)

logger = setup_logger("resolve_doi_prefixes", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Résoudre les préfixes DOI inconnus (RA via doi.org, éditeur via api.crossref.org)"
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        help="Nombre max de DOI samples tentés par préfixe (défaut : 3)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limiter le nombre de préfixes traités (défaut : tous)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Planifier sans appeler les API ni insérer"
    )
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        user_agent = build_user_agent(get_openalex_email(conn))
        metrics = run_resolve_doi_prefixes(
            logger,
            repo=doi_prefix_repository(conn),
            publisher_repo=publisher_repository(conn),
            resolve_ra_fn=lambda doi: resolve_ra(doi, user_agent=user_agent),
            fetch_crossref_prefix_fn=lambda prefix: fetch_crossref_prefix(
                prefix, user_agent=user_agent
            ),
            n_samples=args.samples,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        if not args.dry_run:
            conn.commit()
        logger.info("✓ resolve_doi_prefixes terminé — %s", metrics.as_summary())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
