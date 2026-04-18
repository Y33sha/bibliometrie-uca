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

Usage:
    python create_publications.py              # exécuter
    python create_publications.py --dry-run    # dry-run
"""

import argparse
import os

from psycopg2.extras import RealDictCursor

from db.connection import get_connection
from application.publications import (
    find_or_create as find_or_create_publication,
)
from application.publications import (
    refresh_from_sources,
)
from domain.doc_types import map_doc_type
from infrastructure.log import setup_logger
from domain.publication import normalize_nnt
from domain.normalize import normalize_text

logger = setup_logger("create_publications", os.path.join(os.path.dirname(__file__), "logs"))


def get_orphan_source_publications(cur):
    """Récupère les source_publications sans publication_id ayant au moins
    un source_authorship in_perimeter."""
    cur.execute("""
        SELECT sd.id, sd.source, sd.source_id, sd.doi, sd.title, sd.pub_year,
               sd.doc_type, sd.journal_id, sd.oa_status, sd.language,
               sd.container_title, sd.external_ids,
               sd.is_retracted, sd.biblio, sd.abstract, sd.keywords, sd.topics
        FROM source_publications sd
        WHERE sd.publication_id IS NULL
          AND EXISTS (
              SELECT 1 FROM source_authorships sa
              WHERE sa.source_publication_id = sd.id AND sa.in_perimeter = TRUE
          )
        ORDER BY sd.id
    """)
    return cur.fetchall()


def process_document(cur, doc, dry_run):
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

    # Extraire le NNT depuis external_ids
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

    # Rattacher le source_document
    cur.execute(
        "UPDATE source_publications SET publication_id = %s WHERE id = %s",
        (pub_id, doc["id"]),
    )

    # Recalcul complet des métadonnées depuis toutes les sources
    refresh_from_sources(cur, pub_id)

    return True


def run(dry_run=False):
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        docs = get_orphan_source_publications(cur)
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
