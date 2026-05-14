"""Query service : lectures pour les scripts de fusion cross-source.

Appelé par `application/pipeline/merge/*`. Les scripts détectent des
publications distinctes qui référencent le même document (via NNT ou
identifiant HAL) et les fusionnent. Les fusions métier elles-mêmes
passent par `application.publications.merge_publications`.
"""

from typing import Any

from sqlalchemy import Connection, text


def find_nnt_duplicates(conn: Connection) -> list[dict[str, Any]]:
    """Liste les NNT dont les `source_publications` pointent vers plusieurs publications.

    Retourne des dicts `{nnt, pub_ids, sources}`.
    """
    rows = conn.execute(
        text("""
            SELECT sd.external_ids->>'nnt' AS nnt,
                   array_agg(DISTINCT sd.publication_id ORDER BY sd.publication_id) AS pub_ids,
                   array_agg(DISTINCT sd.source::text ORDER BY sd.source::text) AS sources
            FROM source_publications sd
            WHERE sd.external_ids->>'nnt' IS NOT NULL
              AND sd.publication_id IS NOT NULL
            GROUP BY sd.external_ids->>'nnt'
            HAVING COUNT(DISTINCT sd.publication_id) > 1
            ORDER BY sd.external_ids->>'nnt'
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def fetch_source_publications_with_hal_external_id(
    conn: Connection,
) -> list[dict[str, Any]]:
    """`source_publications` OpenAlex/ScanR qui référencent un `external_ids.hal_id`.

    Retourne `{src_doc_id, source, src_id, src_pub_id, hal_id}` pour chaque ligne.
    """
    rows = conn.execute(
        text("""
            SELECT sd.id AS src_doc_id, sd.source::text AS source,
                   sd.source_id AS src_id, sd.publication_id AS src_pub_id,
                   sd.external_ids->>'hal_id' AS hal_id
            FROM source_publications sd
            WHERE sd.source IN ('openalex', 'scanr')
              AND sd.external_ids->>'hal_id' IS NOT NULL
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def fetch_hal_source_publications(conn: Connection) -> list[dict[str, Any]]:
    """`source_publications` HAL avec leur identifiant HAL et leur `publication_id`."""
    rows = conn.execute(
        text("""
            SELECT id AS hal_doc_id, source_id AS halid, publication_id AS hal_pub_id
            FROM source_publications
            WHERE source = 'hal'
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def link_source_publication_to_publication(
    conn: Connection, source_publication_id: int, publication_id: int
) -> None:
    """Assigne `publication_id` à un `source_publications` donné."""
    conn.execute(
        text("UPDATE source_publications SET publication_id = :pid WHERE id = :sd_id"),
        {"pid": publication_id, "sd_id": source_publication_id},
    )


class PgMergeQueries:
    """Adapter PostgreSQL pour `application.ports.merge.MergeQueries`."""

    def find_nnt_duplicates(self, conn: Connection) -> list[dict[str, Any]]:
        return find_nnt_duplicates(conn)

    def fetch_source_publications_with_hal_external_id(
        self, conn: Connection
    ) -> list[dict[str, Any]]:
        return fetch_source_publications_with_hal_external_id(conn)

    def fetch_hal_source_publications(self, conn: Connection) -> list[dict[str, Any]]:
        return fetch_hal_source_publications(conn)

    def link_source_publication_to_publication(
        self, conn: Connection, source_publication_id: int, publication_id: int
    ) -> None:
        link_source_publication_to_publication(conn, source_publication_id, publication_id)
