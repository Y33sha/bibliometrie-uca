# STATUS: oneshot (2026-11-16)
"""Répare les orphelins laissés par l'exclusion des errata et des avis de rétractation.

La consolidation a supprimé des publications d'errata qui groupaient aussi les enregistrements sources de l'article corrigé : ces enregistrements sources sont restés sans publication, hors de la file de réconciliation. Passent en file de réconciliation :

- les enregistrements sources orphelins d'un type retenu qui partagent un identifiant actif avec un enregistrement source d'erratum ou d'avis ;
- les enregistrements sources d'erratum ou d'avis encore rattachés à une publication.

Usage :
    uv run python -m interfaces.cli.oneshot.requeue_notice_orphans [--dry-run]
    run_pipeline --from publications
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from domain.documents.doc_types import DocType
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger
from infrastructure.sql_fragments import in_clause

log = setup_logger("requeue_notice_orphans", os.path.dirname(__file__))

_NOTICE_TYPES = in_clause(sorted({DocType.ERRATUM.value, DocType.RETRACTION.value}))
_OUT_OF_SCOPE = in_clause(sorted(OUT_OF_SCOPE_DOC_TYPES))

_ORPHANS = f"""
    WITH notice_keys AS (
        SELECT DISTINCT i.id_type, i.id_value
        FROM source_records n JOIN source_record_identifiers i ON i.source_record_id = n.id
        WHERE n.doc_type::text IN {_NOTICE_TYPES} AND i.removed_by IS NULL AND i.role <> 'related'
    )
    SELECT DISTINCT sr.id
    FROM source_records sr
    JOIN source_record_identifiers i
      ON i.source_record_id = sr.id AND i.removed_by IS NULL AND i.role <> 'related'
    JOIN notice_keys k ON k.id_type = i.id_type AND k.id_value = i.id_value
    WHERE sr.publication_id IS NULL AND sr.is_matchable AND sr.doc_type::text NOT IN {_OUT_OF_SCOPE}
"""
"""Orphelins d'un type retenu qui partagent un identifiant actif avec un erratum ou un avis."""

_ATTACHED_NOTICES = f"""
    SELECT id FROM source_records
    WHERE publication_id IS NOT NULL AND doc_type::text IN {_NOTICE_TYPES}
"""


def requeue(conn: Connection, *, dry_run: bool) -> None:
    """Marque pour la réconciliation les orphelins voisins d'un avis et les avis encore rattachés."""
    for label, ids_sql in (("orphelins", _ORPHANS), ("avis rattachés", _ATTACHED_NOTICES)):
        if dry_run:
            count = conn.execute(text(f"SELECT count(*) FROM ({ids_sql}) s")).scalar_one()  # noqa: S608
            log.info("%s à réconcilier : %d", label.capitalize(), count)
        else:
            marked = enqueue(conn, Queue.SOURCE_RECORD_KEYS, ids_sql, {})
            log.info("%s marqués pour la réconciliation : %d", label.capitalize(), marked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="compte sans écrire")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        requeue(conn, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
