"""
Crée les publications pour les source_publications in-perimeter non rattachés.

Phase du pipeline qui s'exécute APRÈS affiliations (quand in_perimeter est
déterminé sur les source_authorships) et AVANT persons/authorships.

Pour chaque source_document sans publication_id et ayant au moins un
source_authorship in_perimeter :
  1. Cherche une publication existante (DOI, NNT, titre+année+journal)
  2. Si trouvée : rattache et enrichit
  3. Si non trouvée : crée la publication

L'orchestrateur dépend du port `PublicationsCreateQueries`. Le point
d'entrée CLI est dans `interfaces/cli/pipeline/create_publications.py`.
"""

import logging
from typing import Any

from sqlalchemy import Connection

from application.ports.publications_create import PublicationsCreateQueries
from application.publications import (
    find_or_create as find_or_create_publication,
)
from application.publications import (
    refresh_from_sources,
)
from domain.normalize import normalize_text
from domain.ports.publication_repository import PublicationRepository
from domain.publication import normalize_nnt
from domain.publications.dedup import has_minimal_publication_metadata
from domain.publications.doc_types import map_doc_type
from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT


def process_document(
    conn: Connection,
    queries: PublicationsCreateQueries,
    doc: Any,
    dry_run: bool,
    *,
    pub_repo: PublicationRepository,
) -> bool:
    """Crée ou rattache une publication pour un source_document orphelin."""
    title = doc["title"] or ""
    pub_year = doc["pub_year"]
    if not has_minimal_publication_metadata(title, pub_year):
        return False

    doi = doc["doi"]
    source = doc["source"]
    doc_type = map_doc_type(doc["doc_type"], source)
    journal_id = doc["journal_id"]
    oa_status = doc["oa_status"] or OA_STATUS_UNKNOWN_DEFAULT
    language = doc["language"]
    container_title = doc["container_title"]

    ext_ids = doc["external_ids"] or {}
    nnt = ext_ids.get("nnt")
    if nnt:
        nnt = normalize_nnt(nnt)

    if dry_run:
        return True

    pub_id, _is_new = find_or_create_publication(
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
        repo=pub_repo,
    )

    if not pub_id:
        return False

    queries.link_source_publication_to_publication(conn, doc["id"], pub_id)
    refresh_from_sources(pub_id, repo=pub_repo)

    return True


def run(
    conn: Connection,
    queries: PublicationsCreateQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
) -> None:
    try:
        docs = queries.fetch_orphan_in_perimeter_source_publications(conn)
        logger.info("%d source_publications in-perimeter sans publication", len(docs))

        if not docs:
            logger.info("Rien a faire.")
            return

        created = 0
        skipped = 0
        for i, doc in enumerate(docs):
            if process_document(conn, queries, doc, dry_run, pub_repo=pub_repo):
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

    except Exception:
        conn.rollback()
        logger.exception("Erreur")
        raise
