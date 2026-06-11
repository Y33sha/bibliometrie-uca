"""Helper de tests : exécute la vraie phase « publications » du pipeline.

Partagé par les tests d'idempotence et de re-traitement, qui ont besoin de
créer **puis dédupliquer** les publications de leurs source_publications
orphelins via les vraies passes (modèle création⇒fusion), sans réimplémenter
l'orchestration.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.publications import (
    create_publications,
    mark_distinct_publications,
    merge_pubs_by_doi,
    merge_pubs_by_hal_id,
    merge_pubs_by_metadata,
    merge_pubs_by_nnt,
    merge_pubs_by_pmid,
)
from infrastructure.queries.pipeline.distinct_publications import PgDistinctPublicationsQueries
from infrastructure.queries.pipeline.merge import PgMergeQueries
from infrastructure.queries.pipeline.metadata_merge import PgMetadataMergeQueries
from infrastructure.queries.pipeline.publications_create import (
    PgPublicationsCreateQueries,
)
from infrastructure.repositories import publication_repository

_logger = logging.getLogger("test_publications_phase")


def create_all_publications(conn: Connection) -> None:
    """Rejoue la phase publications de prod (création⇒fusion) sur les orphelins :
    une publication par `source_publication`, puis marquage des distinctes et
    passes de fusion (identifiants puis métadonnées).

    `commit=False` partout : la fixture `sa_sync_conn` rollback la transaction
    au téardown, on ne doit donc rien committer.
    """
    repo = publication_repository(conn)
    mc_queries = PgPublicationsCreateQueries()
    for doc in mc_queries.fetch_orphan_source_publications(conn):
        create_publications.process_document(
            conn, mc_queries, doc, dry_run=False, pub_repo=repo
        )

    merge_queries = PgMergeQueries()
    mark_distinct_publications.run_mark_distinct(
        conn, PgDistinctPublicationsQueries(), _logger, pub_repo=repo, commit=False
    )
    merge_pubs_by_hal_id.run_merge(conn, merge_queries, _logger, pub_repo=repo, commit=False)
    merge_pubs_by_nnt.run_merge(conn, merge_queries, _logger, pub_repo=repo, commit=False)
    merge_pubs_by_doi.run_merge(conn, merge_queries, _logger, pub_repo=repo, commit=False)
    merge_pubs_by_pmid.run_merge(conn, merge_queries, _logger, pub_repo=repo, commit=False)
    merge_pubs_by_metadata.run_merge(
        conn, PgMetadataMergeQueries(), _logger, pub_repo=repo, commit=False
    )


__all__ = ["create_all_publications"]
