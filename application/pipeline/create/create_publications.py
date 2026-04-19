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

from typing import Any

from application.ports.publications_create import PublicationsCreateQueries
from application.publications import (
    find_or_create as find_or_create_publication,
)
from application.publications import (
    refresh_from_sources,
)
from domain.doc_types import map_doc_type
from domain.normalize import normalize_text
from domain.publication import normalize_nnt


def process_document(cur: Any, queries: PublicationsCreateQueries, doc: Any, dry_run: bool) -> bool:
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

    pub_id, _is_new = find_or_create_publication(
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

    queries.link_source_publication_to_publication(cur, doc["id"], pub_id)
    refresh_from_sources(cur, pub_id)

    return True


def run(
    cur: Any,
    conn: Any,
    queries: PublicationsCreateQueries,
    logger: Any,
    *,
    dry_run: bool = False,
) -> None:
    try:
        docs = queries.fetch_orphan_in_perimeter_source_publications(cur)
        logger.info("%d source_publications in-perimeter sans publication", len(docs))

        if not docs:
            logger.info("Rien a faire.")
            return

        created = 0
        skipped = 0
        for i, doc in enumerate(docs):
            if process_document(cur, queries, doc, dry_run):
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
