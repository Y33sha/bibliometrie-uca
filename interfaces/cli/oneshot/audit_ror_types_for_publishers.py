# STATUS: oneshot (2026-05-26)
"""
Audit (pure lecture) : pour les publishers locaux qui ont un `ror`
non-NULL, fetcher leur enregistrement ROR et reporter la distribution
des combinaisons de `types` (ROR v2 expose `types` comme une LISTE,
ex. `['company', 'funder']`), en y appliquant le mapping figé dans
`domain.publishers.publisher.map_ror_types` pour visualiser ce que
`application.publishers_enrichment.from_ror` écrirait.

Le mapping vit dans `domain.publishers.publisher` et est consommé par
`application.publishers_enrichment.from_ror`. Ce script reste utile en
oneshot pour re-vérifier la distribution si on
veut éventuellement re-arbitrer le mapping (ex. `nonprofit` qui mélange
sociétés savantes et éditeurs nonprofit).

Ne fait AUCUNE écriture en base.

Usage :
    python -m interfaces.cli.oneshot.audit_ror_types_for_publishers [--limit N]
"""

from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict

from sqlalchemy import text

from domain.publishers.publisher import map_ror_types
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.api_limits import ROR_DELAY
from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email
from infrastructure.sources.ror import build_ror_user_agent, fetch_ror_record

log = setup_logger("audit_ror_types_for_publishers", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limiter le nombre de publishers audités (0 = tous)",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        user_agent = build_ror_user_agent(get_polite_pool_email(conn))
        ror_base_url = get_api_base_urls()["ror"]

        sql = """
            SELECT id, name, ror
            FROM publishers
            WHERE ror IS NOT NULL
            ORDER BY id
        """
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        rows = conn.execute(text(sql)).all()
        total = len(rows)
        log.info("%d publishers avec un ROR à auditer.", total)

        if total == 0:
            log.info("Rien à faire.")
            return 0

        # tuple de types → liste de (publisher_id, name, ror)
        by_types: dict[tuple[str, ...], list[tuple[int, str, str]]] = defaultdict(list)
        no_record = 0
        no_types = 0

        for i, row in enumerate(rows, 1):
            record = fetch_ror_record(
                row.ror, base_url=ror_base_url, user_agent=user_agent, logger=log
            )
            time.sleep(ROR_DELAY)
            if record is None:
                no_record += 1
                continue
            types = record.get("types") or []
            if not types:
                no_types += 1
                continue
            key = tuple(sorted(types))
            by_types[key].append((row.id, row.name, row.ror))
            if i % 50 == 0:
                log.info("  %d/%d records ROR fetchés", i, total)

        log.info("─" * 70)
        log.info("Distribution des combinaisons ROR `types` :")
        # Trie par effectif décroissant
        sorted_types = sorted(by_types.items(), key=lambda kv: -len(kv[1]))
        for type_tuple, pubs in sorted_types:
            type_label = "+".join(type_tuple)
            mapping = map_ror_types(list(type_tuple))
            mapping_label = mapping if mapping else "(non mappé)"
            log.info(
                "  %-35s %4d publishers  → %s",
                type_label,
                len(pubs),
                mapping_label,
            )
        log.info("─" * 70)
        log.info("Sans record ROR (404 ou erreur) : %d", no_record)
        log.info("Avec record mais sans `types` : %d", no_types)
        log.info("─" * 70)
        log.info("Exemples par combinaison (max 3 par bucket) :")
        for type_tuple, pubs in sorted_types:
            type_label = "+".join(type_tuple)
            log.info("  [%s]", type_label)
            for pub_id, name, ror in pubs[:3]:
                log.info("    #%d %s (ror=%s)", pub_id, name, ror)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
