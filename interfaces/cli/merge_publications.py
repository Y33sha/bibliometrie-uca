"""
Fusion ad hoc de deux publications doublonnées.

Variante CLI de l'endpoint admin POST /api/admin/duplicates/merge — utile
quand on n'a pas de session HTTP (terminal non auth) ou pour scripter un
nettoyage en lot.

Usage :
    python interfaces/cli/merge_publications.py <target_id> <source_id>           # dry-run
    python interfaces/cli/merge_publications.py <target_id> <source_id> --apply
"""

import argparse
import os
import sys
from typing import Any

from application.publications import merge_publications
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger
from infrastructure.repositories import publication_repository

log = setup_logger("merge_publications", os.path.dirname(__file__))


def _fetch_summary(cur: Any, pub_id: int) -> dict | None:
    cur.execute(
        "SELECT id, title, pub_year, doi, doc_type::text AS doc_type "
        "FROM publications WHERE id = %s",
        (pub_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Fusion ad hoc de deux publications.")
    parser.add_argument("target_id", type=int, help="ID de la publication conservée.")
    parser.add_argument(
        "source_id", type=int, help="ID de la publication absorbée (supprimée à la fin)."
    )
    parser.add_argument("--apply", action="store_true", help="Appliquer (sinon dry-run).")
    args = parser.parse_args()

    if args.target_id == args.source_id:
        log.error("target_id et source_id doivent être différents")
        return 2

    conn = get_connection()
    try:
        cur = conn.cursor()
        target = _fetch_summary(cur, args.target_id)
        source = _fetch_summary(cur, args.source_id)
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

        if not args.apply:
            log.info("[dry-run] ajouter --apply pour exécuter la fusion")
            return 0

        repo = publication_repository(cur)
        merge_publications(cur, args.target_id, args.source_id, repo=repo)
        conn.commit()
        log.info("Fusion %d ← %d effectuée", args.target_id, args.source_id)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
