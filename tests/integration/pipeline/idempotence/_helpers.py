"""Helpers partagés entre plusieurs fichiers de tests d'idempotence."""

from domain.normalize import normalize_text
from domain.publication import normalize_nnt
from domain.publications.doc_types import map_doc_type
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from infrastructure.repositories import publication_repository
from tests.integration.helpers.publications import (
    find_or_create_for_tests as find_or_create_publication,
)


def create_all_publications(conn_or_cur):
    """Crée les publications pour tous les source_publications orphelins.

    Simule la phase 'publications' du pipeline dans les tests. Dispatche
    selon le type (cur psycopg | Connection SA), le temps que tous les
    tests pipeline soient migrés en SA.
    """
    from sqlalchemy import Connection, text

    repo = publication_repository(conn_or_cur)
    if isinstance(conn_or_cur, Connection):
        rows = conn_or_cur.execute(
            text("""
                SELECT id, source, doi, title, pub_year, doc_type, journal_id,
                       oa_status, language, container_title, external_ids
                FROM source_publications WHERE publication_id IS NULL
                ORDER BY id
            """)
        ).all()
        docs = [dict(r._mapping) for r in rows]
    else:
        conn_or_cur.execute("""
            SELECT id, source, doi, title, pub_year, doc_type, journal_id,
                   oa_status, language, container_title, external_ids
            FROM source_publications WHERE publication_id IS NULL
            ORDER BY id
        """)
        docs = list(conn_or_cur.fetchall())

    for doc in docs:
        title = doc["title"] or ""
        pub_year = doc["pub_year"]
        if not title or not pub_year:
            continue
        raw_type = doc["doc_type"] or "other"
        doc_type = map_doc_type(raw_type, doc["source"])
        ext_ids = doc["external_ids"] or {}
        nnt = ext_ids.get("nnt")
        if nnt:
            nnt = normalize_nnt(nnt)
        candidate = Publication(
            id=None,
            title=title,
            title_normalized=normalize_text(title),
            pub_year=pub_year,
            doc_type=doc_type,
            doi=DOI(doc["doi"]) if doc["doi"] else None,
            oa_status=doc["oa_status"] or "unknown",
            journal_id=doc["journal_id"],
            container_title=doc["container_title"],
            language=doc["language"],
        )
        result, _ = find_or_create_publication(candidate, nnt=nnt, allow_create=True, repo=repo)
        if result and result.id is not None:
            if isinstance(conn_or_cur, Connection):
                conn_or_cur.execute(
                    text("UPDATE source_publications SET publication_id = :pid WHERE id = :sid"),
                    {"pid": result.id, "sid": doc["id"]},
                )
            else:
                conn_or_cur.execute(
                    "UPDATE source_publications SET publication_id = %s WHERE id = %s",
                    (result.id, doc["id"]),
                )
            repo.update_sources(result.id)
