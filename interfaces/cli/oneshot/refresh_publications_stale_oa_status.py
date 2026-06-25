# STATUS: oneshot (2026-05-28)
"""Rejoue `refresh_from_sources` sur les publications dont le `oa_status` canonique est plus restrictif que ce que ses `source_publications` permettraient — séquelle d'un bug (corrigé le 2026-05-28) où les rattachements bulk de SP HAL aux publications existantes ne bumpaient pas `sp.updated_at`, ce qui fermait la fenêtre de staleness avant que `refresh_from_sources` ne joue.

Population cible : toute publication où `OA_RANK(best source) > OA_RANK(canonical)`. Capture précisément les ~2117 publications victimes du bug (1287 thèses + 830 autres) où une source HAL ouverte n'a jamais été agrégée dans le canonique.

Le refresh re-déclenche l'agrégation complète : oa_status, abstract, topics, biblio, … — pas uniquement oa_status. Les autres champs peuvent donc bouger aussi, ce qui est l'effet recherché (rattraper toute incohérence latente).

Usage :
    python -m interfaces.cli.oneshot.refresh_publications_stale_oa_status [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from application.publications.core import refresh_from_sources
from domain.publications.metadata import OA_RANK
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import audit_repository, publication_repository

log = setup_logger("refresh_publications_stale_oa_status", os.path.dirname(__file__))

BATCH_COMMIT = 500


def _fetch_target_pub_ids(conn: Connection, limit: int | None) -> list[int]:
    """Sélectionne les publications où une source a un `oa_status` strictement plus ouvert que le canonique (au sens de `OA_RANK`).

    Le mapping `OA_RANK` est inliné en VALUES côté SQL pour évaluer l'inégalité directement en base — pas d'aller-retour Python par publication."""
    rank_rows = ", ".join(f"({rank}, '{status}')" for status, rank in OA_RANK.items())
    sql = f"""
        WITH oa_rank(rank, status) AS (
            VALUES {rank_rows}
        )
        SELECT DISTINCT p.id
        FROM publications p
        JOIN source_publications sp ON sp.publication_id = p.id
        JOIN oa_rank r_pub ON r_pub.status = p.oa_status::text
        JOIN oa_rank r_sp  ON r_sp.status = sp.oa_status
        WHERE sp.oa_status IS NOT NULL
          AND r_sp.rank > r_pub.rank
        ORDER BY p.id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(text(sql)).all()
    return [r.id for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit rien : liste la population cible et sort.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limiter le nombre de publications traitées (0 = toutes).",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        pub_ids = _fetch_target_pub_ids(conn, args.limit or None)
        total = len(pub_ids)
        log.info("%d publications avec oa_status canonique sous-évalué.", total)
        if total == 0:
            return 0

        if args.dry_run:
            log.info("(dry-run : aucune écriture effective)")
            sample = pub_ids[:20]
            log.info("Échantillon : %s%s", sample, " …" if total > len(sample) else "")
            return 0

        pub_repo = publication_repository(conn)
        audit_repo = audit_repository(conn)

        refreshed = 0
        for i, pub_id in enumerate(pub_ids):
            try:
                refresh_from_sources(pub_id, repo=pub_repo, audit_repo=audit_repo)
            except Exception:
                log.exception("  refresh_from_sources crash sur pub_id=%d", pub_id)
                raise
            refreshed += 1
            if (i + 1) % BATCH_COMMIT == 0:
                conn.commit()
                log.info("  %d/%d rafraîchies…", i + 1, total)

        conn.commit()
        log.info("Terminé : %d publications rafraîchies.", refreshed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
