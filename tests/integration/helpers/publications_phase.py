"""Helper de tests : exécute la vraie phase « publications » du pipeline.

Partagé par les tests d'idempotence et de re-traitement, qui ont besoin de
créer/rattacher les publications de leurs source_publications orphelins sans
réimplémenter la cascade de matching.
"""

from sqlalchemy import Connection, text

from application.pipeline.publications.match_or_create_publications import process_document
from infrastructure.queries.pipeline.publications_match_or_create import (
    PgPublicationsMatchOrCreateQueries,
)
from infrastructure.repositories import publication_repository


def create_all_publications(conn: Connection):
    """Crée/rattache les publications des source_publications orphelins via la
    vraie phase A du pipeline (`process_document` par orphelin), pas une cascade
    réimplémentée.

    Ces tests ne jouent pas la phase affiliations : aucun `source_authorship`
    n'est in_perimeter, or la phase A ne traite que les orphelins avec ≥1
    authorship in_perimeter. On sème donc le périmètre à la main
    (`in_perimeter = TRUE`) — équivalent de ce que pose la phase affiliations
    en prod.
    """
    conn.execute(text("UPDATE source_authorships SET in_perimeter = TRUE"))

    queries = PgPublicationsMatchOrCreateQueries()
    repo = publication_repository(conn)
    for doc in queries.fetch_orphan_in_perimeter_source_publications(conn):
        process_document(conn, queries, doc, dry_run=False, pub_repo=repo)


__all__ = ["create_all_publications"]
