# STATUS: oneshot (2026-09-18)
"""Détache de leur revue les notices DataCite dont le conteneur ne désigne pas une revue.

La normalisation DataCite prend le conteneur pour revue selon `container_names_a_journal` : type d'article, de communication, de recueil d'actes, de livre, de chapitre ou de data paper, et conteneur qui ne vient pas d'une citation en texte libre. Une copie d'article déposée dans un entrepôt (GSI, DESY, RWTH), un préprint, un logiciel ou un rapport n'a pas de revue, et le titre de son conteneur reste dans `container_title`.

Ce script applique la règle aux notices existantes. Le type brut vient de `raw_metadata`, où la correction des métadonnées le range quand elle réécrit `doc_type` ; le titre et les pages du conteneur viennent de `biblio`. Une revue rattachée par le préfixe du DOI reste en place. Les publications concernées sont recalculées. La sous-étape de suppression des revues vides de la phase `publishers_journals` supprime ensuite les revues sans enregistrement.

Usage :
    python -m interfaces.cli.oneshot.backfill_detach_datacite_journals             # applique
    python -m interfaces.cli.oneshot.backfill_detach_datacite_journals --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from sqlalchemy import Connection, Row, text

from application.services.publications.core import refresh_from_sources
from domain.source_publications.raw_metadata import raw_value
from domain.sources.datacite import container_names_a_journal
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories.publication_repository import PgPublicationRepository

log = setup_logger("backfill_detach_datacite_journals", os.path.dirname(__file__))

# Notices DataCite rattachées à une revue par leur conteneur, hors rattachement par préfixe DOI.
_CANDIDATES = text("""
    SELECT s.id, s.publication_id, s.journal_id, s.doc_type, s.raw_metadata,
           j.title AS journal_title,
           coalesce(s.biblio->'journal'->>'title', j.title) AS container_title,
           s.biblio->>'first_page' AS first_page, s.biblio->>'last_page' AS last_page
    FROM source_publications s
    JOIN journals j ON j.id = s.journal_id
    WHERE s.source = 'datacite' AND NOT (s.raw_metadata ? 'journal_id')
""")

_DETACH = text("""
    UPDATE source_publications s
    SET journal_id = NULL, container_title = coalesce(s.container_title, j.title)
    FROM journals j
    WHERE j.id = s.journal_id AND s.id = ANY(:ids)
""")


def _to_detach(conn: Connection) -> list[Row[tuple[object, ...]]]:
    return [
        r
        for r in conn.execute(_CANDIDATES).all()
        if not container_names_a_journal(
            raw_value(r.raw_metadata, "doc_type", r.doc_type),
            r.container_title,
            (r.first_page, r.last_page),
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        rows = _to_detach(conn)
        by_journal = Counter((r.journal_id, r.journal_title) for r in rows)
        for (journal_id, title), n in sorted(by_journal.items()):
            log.info(
                "Revue %d « %s » : %d notices détachées",
                journal_id,
                title[:120],
                n,
                extra={"detail": True},
            )
        by_type = Counter(raw_value(r.raw_metadata, "doc_type", r.doc_type) for r in rows)
        for doc_type, n in by_type.most_common():
            log.info("Type brut %s : %d notices détachées", doc_type, n)

        conn.execute(_DETACH, {"ids": [r.id for r in rows]})
        publication_ids = sorted({r.publication_id for r in rows if r.publication_id})
        repo = PgPublicationRepository(conn)
        for publication_id in publication_ids:
            refresh_from_sources(publication_id, repo=repo)

        emptied = conn.execute(
            text("""
                SELECT count(*) FROM journals j
                WHERE j.id = ANY(:ids)
                  AND NOT EXISTS (SELECT 1 FROM source_publications s WHERE s.journal_id = j.id)
                  AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.journal_id = j.id)
            """),
            {"ids": [journal_id for journal_id, _ in by_journal]},
        ).scalar_one()
        log.info(
            "%d notices détachées de %d revues, %d publications recalculées, %d revues vides",
            len(rows),
            len(by_journal),
            len(publication_ids),
            emptied,
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
