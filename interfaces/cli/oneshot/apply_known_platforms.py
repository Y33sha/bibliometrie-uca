# STATUS: oneshot (2026-10-25)
"""Applique au stock la liste des plateformes connues (`domain.platforms.registry`).

Les plateformes prennent le nom et le type que leur donne la liste, à défaut le type entrepôt. Les enregistrements sources des publications dont le DOI a un préfixe de plateforme d'éditeurs passent dans la file de réconciliation : la phase `publications` recalcule ensuite leur éditeur. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.apply_known_platforms [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.platforms.platform import PlatformType
from domain.platforms.registry import KNOWN_PLATFORMS
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("apply_known_platforms", os.path.dirname(__file__))


def rename_platforms(conn: Connection) -> int:
    """Donne à chaque plateforme de la liste le nom de la liste. Rend le nombre de plateformes renommées."""
    known = [(i, p.name) for p in KNOWN_PLATFORMS for i in p.openalex_ids]
    return conn.execute(
        text("""
            UPDATE platforms p SET name = k.name, name_normalized = k.name_normalized
            FROM unnest(CAST(:ids AS text[]), CAST(:names AS text[]), CAST(:normalized AS text[]))
                AS k(openalex_id, name, name_normalized)
            WHERE p.openalex_id = k.openalex_id AND p.name <> k.name
        """),
        {
            "ids": [i for i, _ in known],
            "names": [n for _, n in known],
            "normalized": [normalize_text(n) for _, n in known],
        },
    ).rowcount


def retype_platforms(conn: Connection) -> int:
    """Donne à chaque plateforme le type de la liste, à défaut entrepôt. Rend le nombre de plateformes retypées."""
    known = [(i, p.platform_type.value) for p in KNOWN_PLATFORMS for i in p.openalex_ids]
    return conn.execute(
        text("""
            UPDATE platforms pl SET platform_type = CAST(wanted.platform_type AS platform_type)
            FROM (
                SELECT p.id, coalesce(k.platform_type, :default) AS platform_type
                FROM platforms p
                LEFT JOIN unnest(CAST(:ids AS text[]), CAST(:types AS text[])) AS k(openalex_id, platform_type)
                    ON k.openalex_id = p.openalex_id
            ) wanted
            WHERE pl.id = wanted.id AND pl.platform_type::text <> wanted.platform_type
        """),
        {
            "ids": [i for i, _ in known],
            "types": [t for _, t in known],
            "default": PlatformType.REPOSITORY.value,
        },
    ).rowcount


def enqueue_platform_prefix_records(conn: Connection) -> int:
    """Met dans la file de réconciliation les enregistrements sources des publications à préfixe de plateforme d'éditeurs. Rend leur nombre."""
    prefixes = sorted(
        prefix
        for p in KNOWN_PLATFORMS
        if p.platform_type is PlatformType.PUBLISHER_PLATFORM
        for prefix in p.doi_prefixes
    )
    return enqueue(
        conn,
        Queue.SOURCE_RECORD_KEYS,
        "SELECT sr.id FROM source_records sr JOIN publications p ON p.id = sr.publication_id"
        " WHERE p.doi_prefix = ANY(:prefixes)",
        {"prefixes": prefixes},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        renamed = rename_platforms(conn)
        retyped = retype_platforms(conn)
        queued = enqueue_platform_prefix_records(conn)
        log.info(
            "%d plateformes renommées, %d retypées, %d enregistrements sources à réconcilier",
            renamed,
            retyped,
            queued,
        )
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
