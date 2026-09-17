# STATUS: oneshot (2026-09-17)
"""Fusionne les éditeurs dont les noms ne diffèrent que par le bruit des sources.

Le trouve-ou-crée d'éditeur rapproche les noms par leur clé (`publisher_name_key`) : « Elsevier BV », « Elsevier [1977-....] » et « Elsevier on behalf of … » désignent un seul éditeur. Ce script applique la clé aux éditeurs existants :

1. les éditeurs de même clé sont fusionnés par `merge_publishers` dans celui qui porte le plus de revues, puis le plus de publications ; il prend le nom le plus propre du groupe ; une fusion refusée (revues de même titre aux ISSN divergents) est journalisée et sautée ;
2. chaque éditeur reçoit la forme de nom de sa clé ;
3. un préfixe DOI dont l'éditeur a disparu est rattaché de nouveau par le nom que Crossref ou DataCite lui donne.

Usage :
    python -m interfaces.cli.oneshot.backfill_merge_publisher_name_variants             # applique
    python -m interfaces.cli.oneshot.backfill_merge_publisher_name_variants --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict

from sqlalchemy import Connection, text

from application.services.publishers.core import match_or_create_publisher, merge_publishers
from domain.errors import PublisherMergeBlockedError
from domain.normalize import normalize_text
from domain.publishers.names import publisher_name_key
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries
from infrastructure.pipeline.publishers import PgPublisherGatewayQueries
from infrastructure.repositories.journal_repository import PgJournalRepository
from infrastructure.repositories.publication_repository import PgPublicationRepository
from infrastructure.repositories.publisher_repository import PgPublisherRepository

log = setup_logger("backfill_merge_publisher_name_variants", os.path.dirname(__file__))

_PUBLISHERS = text("""
    SELECT p.id, p.name, p.pub_count, p.openalex_id IS NOT NULL AS has_openalex,
           (SELECT count(*) FROM journals j WHERE j.publisher_id = p.id) AS journals
    FROM publishers p
    ORDER BY p.id
""")


def _cleanest_name(names: list[str]) -> str:
    """Le nom sans crochets ni lieu, pas tout en capitales, le plus accentué hors parenthèses, sans parenthèses, puis le plus court."""
    return min(
        names,
        key=lambda n: (
            "[" in n or ":" in n,
            n.isupper(),
            -sum(c.isalpha() and not c.isascii() for c in re.sub(r"\([^)]*\)", "", n)),
            "(" in n,
            len(n),
            n,
        ),
    )


def _merge_variants(conn: Connection) -> tuple[int, int]:
    groups: dict[str, list] = defaultdict(list)
    for row in conn.execute(_PUBLISHERS):
        key = publisher_name_key(row.name)
        if key:
            groups[key].append(row)
    corrections = PgMetadataCorrectionQueries()
    publishers = PgPublisherRepository(conn)
    journals = PgJournalRepository(conn)
    publications = PgPublicationRepository(conn)
    merged = blocked = 0
    for key, rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: (-r.journals, -r.pub_count, not r.has_openalex, r.id))
        target, sources = rows[0], rows[1:]
        name = _cleanest_name([r.name for r in rows])
        if name != target.name:
            conn.execute(
                text("UPDATE publishers SET name = :name, name_normalized = :nn WHERE id = :id"),
                {"name": name, "nn": normalize_text(name), "id": target.id},
            )
            log.info("Éditeur %d « %s » renommé « %s »", target.id, target.name, name)
        for source in sources:
            savepoint = conn.begin_nested()
            try:
                merge_publishers(
                    target.id,
                    source.id,
                    conn=conn,
                    correction_queries=corrections,
                    publisher_repo=publishers,
                    journal_repo=journals,
                    publication_repo=publications,
                )
            except PublisherMergeBlockedError as e:
                savepoint.rollback()
                blocked += 1
                log.warning(
                    "Fusion refusée : éditeur %d « %s » dans %d « %s » — %s",
                    source.id,
                    source.name,
                    target.id,
                    target.name,
                    "; ".join(f"{b['target_title']} : {b['reason']}" for b in e.blocking_journals),
                )
                continue
            savepoint.commit()
            merged += 1
            log.info(
                "Clé %r : éditeur %d « %s » (%d revues) fusionné dans %d « %s »",
                key,
                source.id,
                source.name,
                source.journals,
                target.id,
                target.name,
            )
    return merged, blocked


def _add_key_forms(conn: Connection) -> int:
    gateway = PgPublisherGatewayQueries(conn)
    before = conn.execute(text("SELECT count(*) FROM publisher_name_forms")).scalar_one()
    for row in conn.execute(text("SELECT id, name FROM publishers ORDER BY id")).all():
        key = publisher_name_key(row.name)
        if key:
            gateway.add_publisher_name_form(row.id, key)
    after = conn.execute(text("SELECT count(*) FROM publisher_name_forms")).scalar_one()
    return after - before


def _reattach_orphan_prefixes(conn: Connection) -> int:
    gateway = PgPublisherGatewayQueries(conn)
    rows = conn.execute(
        text("""
            SELECT prefix, publisher_name_raw FROM doi_prefixes
            WHERE publisher_id IS NULL AND publisher_name_raw IS NOT NULL
              AND publisher_checked_at IS NOT NULL
        """)
    ).all()
    for row in rows:
        matched = match_or_create_publisher(row.publisher_name_raw, repo=gateway)
        if matched is None:
            continue
        conn.execute(
            text("UPDATE doi_prefixes SET publisher_id = :p WHERE prefix = :prefix"),
            {"p": matched[0], "prefix": row.prefix},
        )
        log.info(
            "Préfixe %s rattaché à l'éditeur %d « %s »",
            row.prefix,
            matched[0],
            row.publisher_name_raw,
        )
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        merged, blocked = _merge_variants(conn)
        forms = _add_key_forms(conn)
        prefixes = _reattach_orphan_prefixes(conn)
        log.info(
            "%d éditeurs fusionnés, %d fusions refusées, %d formes de nom ajoutées, %d préfixes rattachés",
            merged,
            blocked,
            forms,
            prefixes,
        )
        if args.dry_run:
            conn.rollback()
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        conn.commit()
        log.info("✓ backfill appliqué")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
