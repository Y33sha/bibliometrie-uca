# STATUS: oneshot (2026-09-17)
"""Détache de leur revue les livres et chapitres dont le conteneur est le livre lui-même.

La normalisation applique deux règles au rattachement d'un document à une revue :

1. un livre ou un chapitre sans ISSN a pour conteneur le livre ; son titre reste dans `container_title`, sauf si une revue typée `proceedings` porte ce titre ;
2. un work OpenAlex dont la source est une plateforme d'ebooks n'a pas de revue.

Ce script applique ces règles aux enregistrements existants. Seul Crossref conserve les ISSN du document : pour les autres sources, les ISSN de la revue en tiennent lieu. Les publications concernées sont recalculées. La sous-étape de suppression des revues vides de la phase `publishers_journals` supprime ensuite les revues sans enregistrement.

Usage :
    python -m interfaces.cli.oneshot.backfill_detach_books_from_journals             # applique
    python -m interfaces.cli.oneshot.backfill_detach_books_from_journals --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

from sqlalchemy import Connection, text

from application.services.publications.core import refresh_from_sources
from domain.journals.containers import container_is_journal
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories.publication_repository import PgPublicationRepository

log = setup_logger("backfill_detach_books_from_journals", os.path.dirname(__file__))

# Enregistrements rattachés hors recueil d'actes, à une revue sans ISSN connu du document ou à une plateforme d'ebooks.
_CANDIDATES = text("""
    SELECT s.id, s.source, s.publication_id, s.journal_id, j.title AS journal_title,
           coalesce(s.raw_metadata->'doc_type'->>'raw', s.doc_type) AS raw_type,
           CASE WHEN s.source = 'crossref' THEN s.external_ids ? 'issn'
                ELSE j.issn IS NOT NULL OR j.eissn IS NOT NULL OR j.issnl IS NOT NULL
           END AS has_issn,
           j.journal_type::text = 'ebook_platform' AS ebook_platform
    FROM source_publications s
    JOIN journals j ON j.id = s.journal_id
    WHERE j.journal_type::text <> 'proceedings'
      AND ((s.source = 'crossref' AND NOT s.external_ids ? 'issn')
           OR (s.source <> 'crossref' AND j.issn IS NULL AND j.eissn IS NULL AND j.issnl IS NULL)
           OR j.journal_type::text = 'ebook_platform')
""")

_DETACH = text("""
    UPDATE source_publications s
    SET journal_id = NULL, container_title = coalesce(s.container_title, j.title)
    FROM journals j
    WHERE j.id = s.journal_id AND s.id = ANY(:ids)
""")


def _to_detach(conn: Connection) -> list:
    rows = conn.execute(_CANDIDATES).all()
    return [
        r
        for r in rows
        if (r.source == "openalex" and r.ebook_platform)
        or not container_is_journal(r.raw_type, r.source, has_issn=r.has_issn)
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
            log.info("Revue %d « %s » : %d enregistrements détachés", journal_id, title, n)
        for source, n in sorted(Counter(r.source for r in rows).items()):
            log.info("Source %s : %d enregistrements détachés", source, n)

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
            "%d enregistrements détachés de %d revues, %d publications recalculées, %d revues vides",
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
