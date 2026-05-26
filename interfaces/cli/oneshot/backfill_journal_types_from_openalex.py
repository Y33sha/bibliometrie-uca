# STATUS: oneshot (2026-05-26)
"""
Backfill `journals.journal_type` à partir d'OpenAlex Sources.

Ré-interroge l'API OpenAlex Sources pour TOUTES les revues ayant un
`openalex_id` (contrairement à la phase enrich régulière qui se restreint
aux revues sans APC). Reporte la distribution des `type` bruts renvoyés
par OpenAlex puis applique le mapping
`domain.journals.journal.map_openalex_source_type`.

Politique d'écrasement par défaut : on écrit la valeur mappée quand
`journal_type` actuel est `NULL` ou `'journal'` (= défaut DB indistinguable
d'un choix admin). On préserve les autres valeurs (choix admin explicites
type `proceedings`/`repository`/etc.) sauf si `--force` est passé.

Usage :
    python -m interfaces.cli.oneshot.backfill_journal_types_from_openalex [--dry-run] [--force] [--limit N]
"""

from __future__ import annotations

import argparse
import os
import time
from collections import Counter

from sqlalchemy import text

from application.pipeline.enrich.enrich_journal_apc import (
    BATCH_SIZE,
    fetch_sources_batch,
)
from application.ports.repositories.journal_repository import JournalUpdateFields
from domain.journals.journal import map_openalex_source_type
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import journal_repository
from infrastructure.sources.api_limits import DOAJ_DELAY
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)

log = setup_logger("backfill_journal_types_from_openalex", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lit OpenAlex et affiche la distribution sans écrire en base.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Écrase aussi les valeurs `journal_type` non-NULL et non-`journal` (sinon préservées).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limiter le nombre de revues traitées (0 = toutes).",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        api_key = get_openalex_api_key(conn)
        mailto = get_polite_pool_email(conn)
        openalex_sources_api = get_api_base_urls(conn)["openalex_sources"]
        repo = journal_repository(conn)

        sql = """
            SELECT id, openalex_id, journal_type
            FROM journals
            WHERE openalex_id IS NOT NULL
            ORDER BY id
        """
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        rows = conn.execute(text(sql)).all()
        total = len(rows)
        log.info("%d revues avec openalex_id à interroger.", total)
        if total == 0:
            return 0

        id_to_current: dict[int, str | None] = {r.id: r.journal_type for r in rows}
        oa_to_journal: dict[str, int] = {r.openalex_id: r.id for r in rows}

        raw_type_counter: Counter[str] = Counter()
        mapped_counter: Counter[str] = Counter()
        unmapped_counter: Counter[str] = Counter()
        no_response = 0
        written = 0
        preserved = 0

        oa_ids_all = list(oa_to_journal.keys())
        for i in range(0, total, BATCH_SIZE):
            batch_oa_ids = oa_ids_all[i : i + BATCH_SIZE]
            sources = fetch_sources_batch(
                batch_oa_ids,
                log,
                openalex_sources_api=openalex_sources_api,
                api_key=api_key,
                mailto=mailto,
            )
            time.sleep(DOAJ_DELAY)

            for oa_id in batch_oa_ids:
                journal_id = oa_to_journal[oa_id]
                source = sources.get(oa_id)
                if not source:
                    no_response += 1
                    continue

                raw_type = source.get("type")
                if raw_type:
                    raw_type_counter[raw_type] += 1

                mapped = map_openalex_source_type(raw_type)
                if mapped is None:
                    if raw_type:
                        unmapped_counter[raw_type] += 1
                    continue

                mapped_counter[mapped] += 1

                current = id_to_current[journal_id]
                overwritable = current is None or current == "journal"
                if not overwritable and not args.force:
                    preserved += 1
                    continue

                if current == mapped:
                    # Idempotent : pas d'écriture inutile.
                    continue

                if not args.dry_run:
                    repo.update_journal_fields(
                        journal_id,
                        JournalUpdateFields(journal_type=mapped),
                    )
                written += 1

            log.info(
                "  %d/%d traitées — %d écrites, %d préservées, %d sans réponse",
                min(i + BATCH_SIZE, total),
                total,
                written,
                preserved,
                no_response,
            )

        if not args.dry_run:
            conn.commit()

        log.info("─" * 60)
        log.info("Distribution OpenAlex `type` (brut) :")
        for raw, n in raw_type_counter.most_common():
            log.info("  %-20s %d", raw, n)
        log.info("─" * 60)
        log.info("Distribution mappée (journal_type) :")
        for mapped_value, n in mapped_counter.most_common():
            log.info("  %-20s %d", mapped_value, n)
        if unmapped_counter:
            log.info("─" * 60)
            log.info("Types OpenAlex sans mapping (skip) :")
            for raw, n in unmapped_counter.most_common():
                log.info("  %-20s %d", raw, n)
        log.info("─" * 60)
        log.info(
            "Bilan : %d écrites, %d préservées (admin explicite), %d sans réponse, %d total",
            written,
            preserved,
            no_response,
            total,
        )
        if args.dry_run:
            log.info("(dry-run : aucune écriture effective)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
