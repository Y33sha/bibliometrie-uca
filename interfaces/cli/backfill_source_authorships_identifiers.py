"""Backfill `source_authorships.identifiers` depuis `source_persons`.

Construit le JSONB d'identifiants normalisés à partir des champs
existants de `source_persons`, pour chaque `source_authorships` qui y
est rattachée (`source_person_id IS NOT NULL`).

Mapping des champs :
    sp.orcid                          → identifiers.orcid
    sp.idref                          → identifiers.idref
    sp.source_ids->>'idhal'           → identifiers.idhal
    sp.source_ids->>'hal_person_id'   → identifiers.hal_person_id
    sp.source_ids->>'researcher_id'   → identifiers.researcher_id (WoS)

Les rows où aucun identifiant n'est présent ne sont pas écrites
(``identifiers`` reste NULL — cf. ``jsonb_strip_nulls``).

Traitement par batches via cursor sur ``sa.id`` (clé primaire indexée).
Logs de progression et ETA toutes les batches. Par défaut idempotent :
les rows où ``identifiers`` est déjà non-null sont skippées.

Usage :
    python -m interfaces.cli.backfill_source_authorships_identifiers
    python -m interfaces.cli.backfill_source_authorships_identifiers --batch-size 50000
    python -m interfaces.cli.backfill_source_authorships_identifiers --dry-run
    python -m interfaces.cli.backfill_source_authorships_identifiers --force  # réécrit tout
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Any

from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger

logger = setup_logger(
    "backfill_source_authorships_identifiers", os.path.dirname(__file__)
)


_BUILD_IDENTIFIERS = """
    jsonb_strip_nulls(jsonb_build_object(
        'orcid', sp.orcid,
        'idref', sp.idref,
        'idhal', sp.source_ids->>'idhal',
        'hal_person_id', sp.source_ids->>'hal_person_id',
        'researcher_id', sp.source_ids->>'researcher_id'
    ))
"""


def get_total_count(cur: Any, *, force: bool) -> int:
    """Total de `source_authorships` candidats au backfill."""
    where_extra = "" if force else " AND identifiers IS NULL"
    cur.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM source_authorships
        WHERE source_person_id IS NOT NULL{where_extra}
        """
    )
    return cur.fetchone()["n"]


def get_max_id(cur: Any) -> int:
    cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM source_authorships")
    return cur.fetchone()["m"]


def process_batch(
    cur: Any, last_id: int, batch_size: int, *, force: bool, dry_run: bool
) -> tuple[int | None, int, int]:
    """Traite un batch et retourne (max_id, batch_actuel, n_with_ids)."""
    where_extra = "" if force else "AND sa.identifiers IS NULL"

    # Étape 1 : compter le batch et combien auront des identifiants non-vides
    cur.execute(
        f"""
        WITH batch AS (
            SELECT sa.id, sa.source_person_id
            FROM source_authorships sa
            WHERE sa.id > %s
              AND sa.source_person_id IS NOT NULL
              {where_extra}
            ORDER BY sa.id
            LIMIT %s
        )
        SELECT
            COUNT(*) AS batch_size,
            MAX(b.id) AS max_id,
            COUNT(*) FILTER (WHERE {_BUILD_IDENTIFIERS} != '{{}}'::jsonb) AS with_ids
        FROM batch b
        LEFT JOIN source_persons sp ON sp.id = b.source_person_id
        """,
        (last_id, batch_size),
    )
    row = cur.fetchone()
    if row["batch_size"] == 0:
        return None, 0, 0

    if dry_run:
        return row["max_id"], row["batch_size"], row["with_ids"]

    # Étape 2 : UPDATE
    cur.execute(
        f"""
        WITH batch AS (
            SELECT sa.id
            FROM source_authorships sa
            WHERE sa.id > %s
              AND sa.source_person_id IS NOT NULL
              {where_extra}
            ORDER BY sa.id
            LIMIT %s
        )
        UPDATE source_authorships sa
        SET identifiers = ids.val
        FROM (
            SELECT sa2.id, {_BUILD_IDENTIFIERS} AS val
            FROM source_authorships sa2
            JOIN batch b ON b.id = sa2.id
            JOIN source_persons sp ON sp.id = sa2.source_person_id
        ) ids
        WHERE sa.id = ids.id
          AND ids.val != '{{}}'::jsonb
        """,
        (last_id, batch_size),
    )
    n_updated = cur.rowcount
    return row["max_id"], row["batch_size"], n_updated


def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}min"
    return f"{seconds / 3600:.1f}h"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Nombre de rows par batch (défaut : 10000)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Réécrit même les rows où `identifiers` est déjà non-null",
    )
    parser.add_argument("--dry-run", action="store_true", help="Aucun UPDATE")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    total = get_total_count(cur, force=args.force)
    max_id = get_max_id(cur)
    logger.info(f"Total candidats : {total}")
    logger.info(f"Max id source_authorships : {max_id}")
    if total == 0:
        logger.info("Rien à faire.")
        conn.close()
        return
    if args.dry_run:
        logger.info("Mode --dry-run : aucun UPDATE")
    if args.force:
        logger.info("Mode --force : réécriture des rows déjà peuplées")

    t0 = time.time()
    last_id = 0
    processed = 0
    populated = 0

    try:
        while last_id < max_id:
            new_max, batch_actual, n_with = process_batch(
                cur,
                last_id,
                args.batch_size,
                force=args.force,
                dry_run=args.dry_run,
            )
            if new_max is None:
                break

            if not args.dry_run:
                conn.commit()

            processed += batch_actual
            populated += n_with
            last_id = new_max

            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total - processed) / rate if rate > 0 else 0
            pct = 100 * processed / total if total else 100
            logger.info(
                f"  {processed}/{total} ({pct:.1f}%), "
                f"{populated} avec identifiants, "
                f"{rate:.0f} rows/s, ETA {fmt_duration(eta)}"
            )

        elapsed = time.time() - t0
        logger.info(
            f"\nTerminé en {fmt_duration(elapsed)} : {populated} rows mises à jour"
        )
    except KeyboardInterrupt:
        if not args.dry_run:
            conn.commit()
        logger.warning(
            f"Interrompu après {processed} rows ({populated} avec identifiants). "
            "État cohérent — relancer reprend depuis le dernier batch commité."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
