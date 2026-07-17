# STATUS: oneshot (2026-05-08)
"""
Fusion ad hoc de deux publications doublonnées.

Variante CLI de l'endpoint admin POST /api/admin/duplicates/merge — utile
quand on n'a pas de session HTTP (terminal non auth) ou pour scripter un
nettoyage en lot.

Usage :
    python -m interfaces.cli.maintenance.merge_publications <target_id> <source_id>              # applique
    python -m interfaces.cli.maintenance.merge_publications <target_id> <source_id> --dry-run    # aperçu
"""

import argparse
import os
import sys
from typing import Any

from sqlalchemy import Connection, text

from application.services.publications.core import merge_publications
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import publication_repository

log = setup_logger("merge_publications", os.path.dirname(__file__))


def _fetch_summary(conn: Connection, pub_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT id, title, pub_year, doi, doc_type::text AS doc_type "
            "FROM publications WHERE id = :id"
        ),
        {"id": pub_id},
    ).one_or_none()
    return dict(row._mapping) if row else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Fusion ad hoc de deux publications.")
    parser.add_argument("target_id", type=int, help="ID de la publication conservée.")
    parser.add_argument(
        "source_id", type=int, help="ID de la publication absorbée (supprimée à la fin)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Aperçu : n'exécute pas la fusion.")
    args = parser.parse_args()

    if args.target_id == args.source_id:
        log.error("target_id et source_id doivent être différents")
        return 2

    conn = get_sync_engine().connect()
    try:
        target = _fetch_summary(conn, args.target_id)
        source = _fetch_summary(conn, args.source_id)
        if not target:
            log.error("Cible %d introuvable", args.target_id)
            return 2
        if not source:
            log.error("Source %d introuvable", args.source_id)
            return 2

        log.info(
            "Cible  (%d) : %s | %s | doi=%s",
            target["id"],
            target["pub_year"],
            target["doc_type"],
            target["doi"],
        )
        log.info("        title=%s", (target["title"] or "")[:120])
        log.info(
            "Source (%d) : %s | %s | doi=%s",
            source["id"],
            source["pub_year"],
            source["doc_type"],
            source["doi"],
        )
        log.info("        title=%s", (source["title"] or "")[:120])

        if args.dry_run:
            log.info("[dry-run] fusion non exécutée ; retirer --dry-run pour l'appliquer")
            return 0

        repo = publication_repository(conn)
        merge_publications(args.target_id, args.source_id, repo=repo)
        conn.commit()
        log.info("Fusion %d ← %d effectuée", args.target_id, args.source_id)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
