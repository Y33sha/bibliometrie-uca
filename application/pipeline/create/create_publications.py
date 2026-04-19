"""
Crée les publications pour les source_publications in-perimeter non rattachés.

Phase du pipeline qui s'exécute APRÈS affiliations (quand in_perimeter est
déterminé sur les source_authorships) et AVANT persons/authorships.

Pour chaque source_document sans publication_id et ayant au moins un
source_authorship in_perimeter :
  1. Cherche une publication existante (DOI, NNT, titre+année+journal)
  2. Si trouvée : rattache et enrichit
  3. Si non trouvée : crée la publication

Les source_publications hors périmètre restent sans publication_id.

Le SQL est isolé dans `infrastructure/db/queries/publications_create.py`
et `infrastructure/db/queries/merge.py`.

Usage:
    python create_publications.py              # exécuter
    python create_publications.py --dry-run    # dry-run
"""

import argparse
import os
from typing import Any

from application.publications import (
    find_or_create as find_or_create_publication,
)
from application.publications import (
    refresh_from_sources,
)
from domain.doc_types import map_doc_type
from domain.normalize import normalize_text
from domain.publication import normalize_nnt
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.merge import link_source_publication_to_publication
from infrastructure.db.queries.publications_create import (
    fetch_orphan_in_perimeter_source_publications,
)
from infrastructure.log import setup_logger

logger = setup_logger("create_publications", os.path.join(os.path.dirname(__file__), "logs"))


def process_document(cur: Any, doc: Any, dry_run: Any) -> Any:
    """Crée ou rattache une publication pour un source_document orphelin."""
    title = doc["title"] or ""
    pub_year = doc["pub_year"]
    if not title or not pub_year:
        return False

    doi = doc["doi"]
    source = doc["source"]
    doc_type = map_doc_type(doc["doc_type"], source)
    journal_id = doc["journal_id"]
    oa_status = doc["oa_status"] or "unknown"
    language = doc["language"]
    container_title = doc["container_title"]

    ext_ids = doc["external_ids"] or {}
    nnt = ext_ids.get("nnt")
    if nnt:
        nnt = normalize_nnt(nnt)

    if dry_run:
        return True

    pub_id, is_new = find_or_create_publication(
        cur,
        title=title,
        title_normalized=normalize_text(title),
        pub_year=pub_year,
        doc_type=doc_type,
        doi=doi,
        nnt=nnt,
        oa_status=oa_status,
        journal_id=journal_id,
        container_title=container_title,
        language=language,
        allow_create=True,
    )

    if not pub_id:
        return False

    link_source_publication_to_publication(cur, doc["id"], pub_id)
    refresh_from_sources(cur, pub_id)

    return True


def run(dry_run: Any = False) -> Any:
    conn = get_connection()
    try:
        cur = conn.cursor()

        docs = fetch_orphan_in_perimeter_source_publications(cur)
        logger.info("%d source_publications in-perimeter sans publication", len(docs))

        if not docs:
            logger.info("Rien a faire.")
            conn.close()
            return

        created = 0
        skipped = 0
        for i, doc in enumerate(docs):
            if process_document(cur, doc, dry_run):
                created += 1
            else:
                skipped += 1

            if (i + 1) % 500 == 0:
                if not dry_run:
                    conn.commit()
                logger.info("  %d/%d traités...", i + 1, len(docs))

        if dry_run:
            logger.info("DRY-RUN : %d publications à creer, %d ignorées", created, skipped)
            conn.rollback()
        else:
            conn.commit()
            logger.info(
                "Terminé : %d publications créées/rattachées, %d ignorées", created, skipped
            )

        cur.close()
        conn.close()

    except Exception:
        conn.rollback()
        logger.exception("Erreur")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cree les publications pour les source_publications in-perimeter orphelins"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
