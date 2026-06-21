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
    SharedKeyPair,
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


# Paires de publications distinctes (DOI distincts) partageant une clé de confirmation. Les clés
# vivent sur `source_publications.external_ids` ; une publication les hérite de ses SP rattachées.
# `k1.pid < k2.pid` produit chaque paire une seule fois et fixe `a_id < b_id`. Le `DISTINCT` fusionne
# les paires qui partagent plusieurs clés.
_SHARED_KEY_PAIRS_SQL = text("""
    WITH pub_keys AS (
        SELECT sp.publication_id AS pid, 'hal_id' AS ktype, h AS kval
        FROM source_publications sp
        CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids->'hal_id') h
        WHERE sp.publication_id IS NOT NULL
          AND jsonb_typeof(sp.external_ids->'hal_id') = 'array'
        UNION
        SELECT sp.publication_id, 'arxiv_id', sp.external_ids->>'arxiv_id'
        FROM source_publications sp
        WHERE sp.publication_id IS NOT NULL AND sp.external_ids->>'arxiv_id' IS NOT NULL
        UNION
        SELECT sp.publication_id, 'pmid', sp.external_ids->>'pmid'
        FROM source_publications sp
        WHERE sp.publication_id IS NOT NULL AND sp.external_ids->>'pmid' IS NOT NULL
        UNION
        SELECT sp.publication_id, 'nnt', sp.external_ids->>'nnt'
        FROM source_publications sp
        WHERE sp.publication_id IS NOT NULL AND sp.external_ids->>'nnt' IS NOT NULL
    )
    SELECT DISTINCT
        p1.id AS a_id, p1.doc_type AS a_doc_type, p1.doi AS a_doi,
        p2.id AS b_id, p2.doc_type AS b_doc_type, p2.doi AS b_doi
    FROM pub_keys k1
    JOIN pub_keys k2 ON k1.ktype = k2.ktype AND k1.kval = k2.kval AND k1.pid < k2.pid
    JOIN publications p1 ON p1.id = k1.pid
    JOIN publications p2 ON p2.id = k2.pid
    WHERE p1.doi IS NOT NULL AND p2.doi IS NOT NULL
      AND lower(p1.doi) <> lower(p2.doi)
""")


def fetch_shared_key_pairs(conn: Connection) -> list[SharedKeyPair]:
    rows = conn.execute(_SHARED_KEY_PAIRS_SQL).all()
    return [
        SharedKeyPair(r.a_id, r.a_doc_type, r.a_doi, r.b_id, r.b_doc_type, r.b_doi) for r in rows
    ]


def _insert_relation_edges(conn: Connection, edges: list[RelationEdge]) -> int:
    """Insère `edges` en résolvant la cible (`target_publication_id` par LEFT JOIN sur le DOI),
    en écartant les auto-relations et en dédoublonnant par la PK. Un seul aller-retour bulk via
    `jsonb_to_recordset`. Retourne le nombre de lignes insérées."""
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


def replace_declared_relations(conn: Connection, edges: list[RelationEdge]) -> int:
    """Remplace les relations déclarées : purge les `source` datacite/crossref, puis insère
    `edges`."""
    conn.execute(text("DELETE FROM publication_relations WHERE source IN ('datacite', 'crossref')"))
    return _insert_relation_edges(conn, edges)


def replace_shared_key_relations(conn: Connection, edges: list[RelationEdge]) -> int:
    """Remplace les relations issues des clés partagées : purge la `source` shared_key, puis insère
    `edges`."""
    conn.execute(text("DELETE FROM publication_relations WHERE source = 'shared_key'"))
    return _insert_relation_edges(conn, edges)


class PgPublicationRelationsQueries(PublicationRelationsQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.relations.PublicationRelationsQueries`."""

    def fetch_declared_relation_sources(self, conn: Connection) -> list[DeclaredRelationSource]:
        return fetch_declared_relation_sources(conn)

    def replace_declared_relations(self, conn: Connection, edges: list[RelationEdge]) -> int:
        return replace_declared_relations(conn, edges)

    def fetch_shared_key_pairs(self, conn: Connection) -> list[SharedKeyPair]:
        return fetch_shared_key_pairs(conn)

    def replace_shared_key_relations(self, conn: Connection, edges: list[RelationEdge]) -> int:
        return replace_shared_key_relations(conn, edges)
