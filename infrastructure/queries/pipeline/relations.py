"""Query service : SQL de la phase `relations`.

Appelé par `application/pipeline/relations/populate_relations.py`. Implémente le port
`application.ports.pipeline.relations.PublicationRelationsQueries`.
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.relations import (
    DeclaredRelationSource,
    PublicationRelationsQueries,
    RelationEdge,
)


def fetch_declared_relation_sources(conn: Connection) -> list[DeclaredRelationSource]:
    rows = conn.execute(
        text("""
            SELECT sp.publication_id, sp.source::text AS source, sp.meta
            FROM source_publications sp
            WHERE sp.publication_id IS NOT NULL
              AND (
                    (sp.source = 'datacite' AND sp.meta ? 'related_identifiers')
                 OR (sp.source = 'crossref' AND sp.meta ? 'relation')
              )
        """)
    ).all()
    return [DeclaredRelationSource(r.publication_id, r.source, r.meta) for r in rows]


def replace_declared_relations(conn: Connection, edges: list[RelationEdge]) -> int:
    """Remplace les relations déclarées : purge les `source` datacite/crossref, puis insère
    `edges` en résolvant la cible (`target_publication_id`), en écartant les auto-relations
    et en dédoublonnant par la PK. Un seul aller-retour bulk via `jsonb_to_recordset`."""
    conn.execute(text("DELETE FROM publication_relations WHERE source IN ('datacite', 'crossref')"))
    if not edges:
        return 0
    payload = [
        {"f": e.from_publication_id, "t": e.relation_type, "d": e.target_doi, "s": e.source}
        for e in edges
    ]
    stmt = text("""
        INSERT INTO publication_relations
            (from_publication_id, relation_type, target_doi, target_publication_id, source)
        SELECT e.f, e.t::relation_type, e.d, p.id, e.s
        FROM jsonb_to_recordset(:payload) AS e(f int, t text, d text, s text)
        LEFT JOIN publications p ON lower(p.doi) = e.d
        WHERE p.id IS NULL OR p.id <> e.f
        ON CONFLICT (from_publication_id, relation_type, target_doi) DO NOTHING
    """).bindparams(bindparam("payload", type_=JSONB))
    return conn.execute(stmt, {"payload": payload}).rowcount


class PgPublicationRelationsQueries(PublicationRelationsQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.relations.PublicationRelationsQueries`."""

    def fetch_declared_relation_sources(self, conn: Connection) -> list[DeclaredRelationSource]:
        return fetch_declared_relation_sources(conn)

    def replace_declared_relations(self, conn: Connection, edges: list[RelationEdge]) -> int:
        return replace_declared_relations(conn, edges)
