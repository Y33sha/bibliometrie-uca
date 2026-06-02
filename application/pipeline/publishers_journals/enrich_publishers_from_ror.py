"""
Sub-step de la phase pipeline `publishers_journals` — types
`publisher_type` dérivés des records ROR.

Pour chaque publisher avec `ror IS NOT NULL AND publisher_type='unknown'`,
fetche l'API ROR v2 (via le `RorFetcher` injecté par la composition
root) et mappe `types` (liste) vers notre enum via
`domain.publishers.publisher.map_ror_types`. Politique d'écrasement
« unknown only » : ne touche pas les valeurs admin explicites (cf.
décision 7 du chantier).

Mapping figé à l'audit Phase 3 (cf. roadmap) :
- ROR `education` → `academic_institution`
- ROR `archive` → `repository`
- ROR `company` → `commercial`
- ROR `nonprofit` → `learned_society`
- ROR `government` / `facility` / `other` / `healthcare` / `funder` seul
  → skip (= laissé `unknown`)

ROR n'a pas de bulk endpoint par liste d'IDs : 1 req par publisher.
Volume cible ≈ 400 publishers, ~60 s avec `ROR_DELAY=0.15`.

Le fetcher concret vit dans `infrastructure/sources/ror.py` ; il est
injecté par la composition root pour respecter l'étanchéité DDD
(application n'importe pas infrastructure).
"""

import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection

from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdateFields,
)
from domain.publishers.publisher import map_ror_types

type RorFetcher = Callable[[str], dict[str, Any] | None]
"""Signature : ``(ror) → record JSON ou None (404 / erreur)``."""

COMMIT_EVERY = 50


def run_enrich_publishers_from_ror(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    publisher_repo: PublisherRepository,
    fetcher: RorFetcher,
    limit: int = 0,
    dry_run: bool = False,
    rate_delay: float = 0.15,
) -> None:
    try:
        publishers = queries.fetch_publishers_needing_publisher_type_from_ror(
            conn, limit=limit or None
        )
        total = len(publishers)
        logger.info(f"{total} publishers à typer via ROR (avec ror, publisher_type='unknown').")

        if total == 0:
            logger.info("Rien à faire.")
            return

        mapped_count = 0
        unmapped_count = 0
        no_record = 0
        no_types = 0
        type_counter: Counter[str] = Counter()

        for i, (publisher_id, ror) in enumerate(publishers, 1):
            record = fetcher(ror)
            time.sleep(rate_delay)
            if record is None:
                no_record += 1
                continue
            ror_types = record.get("types") or []
            if not ror_types:
                no_types += 1
                continue
            mapped = map_ror_types(ror_types)
            if mapped is None:
                unmapped_count += 1
                continue

            if not dry_run:
                publisher_repo.update_publisher_fields(
                    publisher_id, PublisherUpdateFields(publisher_type=mapped)
                )
            mapped_count += 1
            type_counter[mapped] += 1

            if not dry_run and i % COMMIT_EVERY == 0:
                conn.commit()
                logger.info(f"  {i}/{total} traités, {mapped_count} typés")

        if not dry_run:
            conn.commit()

        logger.info(
            f"Terminé : {mapped_count}/{total} publishers typés via ROR "
            f"({unmapped_count} non mappés, {no_record} sans record ROR, "
            f"{no_types} sans types ROR)."
        )
        if type_counter:
            distrib = ", ".join(f"{t}={n}" for t, n in type_counter.most_common())
            logger.info(f"Distribution publisher_type posés : {distrib}")

    except KeyboardInterrupt:
        # Ctrl+C peut frapper en plein execute (transaction avortée → `commit()`
        # lèverait `PendingRollbackError`) : on rollback le batch en cours et on
        # re-raise pour laisser `run_pipeline` arrêter proprement le pipeline.
        conn.rollback()
        logger.warning("Interruption — batches déjà committés conservés.")
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
