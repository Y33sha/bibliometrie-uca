"""Query service : SQL de la phase `relations`.

Appelé par `application/pipeline/relations/phase.py`. Implémente le port `application.ports.pipeline.relations.PublicationRelationsQueries`.
"""

from sqlalchemy import Connection, bindparam, text

from application.ports.pipeline.relations import (
    DeclaredRelationSource,
    PublicationRelationsQueries,
    RelationEdge,
    SharedKeyPair,
    TitleMatch,
)
from domain.publications.doc_types import DocType
from domain.source_publications.keys import DISCRIMINANT_TITLE_MIN_LENGTH, ConfirmationKey
from domain.sources.registry import Source
from infrastructure.db.jsonb import Jsonb

# Écart d'années toléré entre une œuvre dépendante et son parent, dans les deux sens : un erratum suit son article (parent dans `[année − N … année]`), une version publiée suit son preprint (parent dans `[année … année + N]`).
_TITLE_MATCH_YEAR_WINDOW = 2

# Une ligne `pub_keys` par clé de confirmation scalaire d'`external_ids` ; `hal_id` (array) a son propre bras.
_SCALAR_KEY_ROWS = "".join(
    f"""
        UNION
        SELECT sp.publication_id, '{k}', sp.external_ids->>'{k}'
        FROM source_publications sp
        WHERE sp.publication_id IS NOT NULL AND sp.external_ids->>'{k}' IS NOT NULL"""
    for k in (ConfirmationKey.ARXIV_ID, ConfirmationKey.PMID, ConfirmationKey.NNT)
)

# Paires de publications distinctes (DOI distincts) partageant une clé de confirmation (`source_publications.external_ids`, héritée par la publication). `k1.pid < k2.pid` produit chaque paire une fois ; le `DISTINCT` fusionne les clés multiples.
_SHARED_KEY_PAIRS_SQL = text(f"""
    WITH pub_keys AS (
        SELECT sp.publication_id AS pid, '{ConfirmationKey.HAL_ID}' AS ktype, h AS kval
        FROM source_publications sp
        CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids->'{ConfirmationKey.HAL_ID}') h
        WHERE sp.publication_id IS NOT NULL
          AND jsonb_typeof(sp.external_ids->'{ConfirmationKey.HAL_ID}') = 'array'
        {_SCALAR_KEY_ROWS}
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

# Signal #3 — rapprochement par titre de l'œuvre dépendante (erratum, preprint) à son parent. Erratum : titre parent = suffixe du titre erratum. Preprint : titre identique. Garde d'ambiguïté : un seul candidat substantiel, sinon abstention.
_ERRATUM_TITLE_MATCHES_SQL = text(f"""
    WITH child AS (
        SELECT id, title_normalized AS t, pub_year AS y
        FROM publications
        WHERE doc_type = '{DocType.ERRATUM.value}'
          AND title_normalized IS NOT NULL AND pub_year IS NOT NULL
    ),
    candidate AS (
        SELECT c.id AS child_id, p.id AS parent_id, p.doi AS parent_doi,
               (p.doc_type::text NOT IN ('{DocType.PREPRINT.value}', '{DocType.DATASET.value}'))
                   AS substantive
        FROM child c
        JOIN publications p
          ON p.id <> c.id
         AND p.doc_type <> '{DocType.ERRATUM.value}'
         AND length(p.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
         AND p.pub_year BETWEEN c.y - {_TITLE_MATCH_YEAR_WINDOW} AND c.y
         AND right(c.t, length(p.title_normalized)) = p.title_normalized
    ),
    substantive_count AS (
        SELECT child_id, count(*) FILTER (WHERE substantive) AS n
        FROM candidate GROUP BY child_id
    )
    SELECT c.child_id, c.parent_id, c.parent_doi
    FROM candidate c
    JOIN substantive_count s ON s.child_id = c.child_id
    WHERE s.n = 1 AND c.substantive
""")

# Preprint → version publiée : titre identique, parent publié dans [année … année + 2]. Garde d'ambiguïté : un seul candidat substantiel (hors `dataset`) au même titre.
_PREPRINT_TITLE_MATCHES_SQL = text(f"""
    WITH child AS (
        SELECT id, title_normalized AS t, pub_year AS y
        FROM publications
        WHERE doc_type = '{DocType.PREPRINT.value}' AND title_normalized IS NOT NULL
          AND length(title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH} AND pub_year IS NOT NULL
    ),
    candidate AS (
        SELECT c.id AS child_id, p.id AS parent_id, p.doi AS parent_doi,
               (p.doc_type::text <> '{DocType.DATASET.value}') AS substantive
        FROM child c
        JOIN publications p
          ON p.doc_type <> '{DocType.PREPRINT.value}'
         AND p.title_normalized = c.t
         AND length(p.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
         AND p.pub_year BETWEEN c.y AND c.y + {_TITLE_MATCH_YEAR_WINDOW}
    ),
    substantive_count AS (
        SELECT child_id, count(*) FILTER (WHERE substantive) AS n
        FROM candidate GROUP BY child_id
    )
    SELECT c.child_id, c.parent_id, c.parent_doi
    FROM candidate c
    JOIN substantive_count s ON s.child_id = c.child_id
    WHERE s.n = 1 AND c.substantive
""")


class PgPublicationRelationsQueries(PublicationRelationsQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.relations.PublicationRelationsQueries`."""

    def fetch_declared_relation_sources(self, conn: Connection) -> list[DeclaredRelationSource]:
        rows = conn.execute(
            text(f"""
                SELECT sp.publication_id, sp.source::text AS source, sp.meta
                FROM source_publications sp
                WHERE sp.publication_id IS NOT NULL
                  AND (
                        (sp.source = '{Source.DATACITE.value}' AND sp.meta ? 'related_identifiers')
                     OR (sp.source = '{Source.CROSSREF.value}' AND sp.meta ? 'relation')
                  )
            """)
        ).all()
        return [DeclaredRelationSource(r.publication_id, r.source, r.meta) for r in rows]

    def fetch_shared_key_pairs(self, conn: Connection) -> list[SharedKeyPair]:
        rows = conn.execute(_SHARED_KEY_PAIRS_SQL).all()
        return [
            SharedKeyPair(r.a_id, r.a_doc_type, r.a_doi, r.b_id, r.b_doc_type, r.b_doi)
            for r in rows
        ]

    def fetch_declared_related_pairs(self, conn: Connection) -> set[frozenset[int]]:
        rows = conn.execute(
            text(f"""
                SELECT from_publication_id AS a, target_publication_id AS b
                FROM publication_relations
                WHERE source IN ('{Source.DATACITE.value}', '{Source.CROSSREF.value}')
                  AND target_publication_id IS NOT NULL
            """)
        ).all()
        return {frozenset((r.a, r.b)) for r in rows}

    def fetch_erratum_title_matches(self, conn: Connection) -> list[TitleMatch]:
        rows = conn.execute(_ERRATUM_TITLE_MATCHES_SQL).all()
        return [TitleMatch(r.child_id, r.parent_id, r.parent_doi) for r in rows]

    def fetch_preprint_title_matches(self, conn: Connection) -> list[TitleMatch]:
        rows = conn.execute(_PREPRINT_TITLE_MATCHES_SQL).all()
        return [TitleMatch(r.child_id, r.parent_id, r.parent_doi) for r in rows]

    def rebuild_relations(self, conn: Connection, edges: list[RelationEdge]) -> int:
        conn.execute(text("DELETE FROM publication_relations"))
        if not edges:
            return 0
        payload = [
            {
                "f": e.from_publication_id,
                "t": e.relation_type,
                "d": e.target_doi,
                "p": e.target_publication_id,
                "s": e.source,
            }
            for e in edges
        ]
        stmt = text("""
            INSERT INTO publication_relations
                (from_publication_id, relation_type, target_doi, target_publication_id, source)
            SELECT e.f, e.t::relation_type, e.d, COALESCE(e.p, p.id), e.s
            FROM jsonb_to_recordset(:payload) AS e(f int, t text, d text, p int, s text)
            LEFT JOIN publications p ON e.p IS NULL AND e.d IS NOT NULL AND lower(p.doi) = e.d
            WHERE COALESCE(e.p, p.id) IS NULL OR COALESCE(e.p, p.id) <> e.f
            ON CONFLICT ON CONSTRAINT publication_relations_uq DO NOTHING
        """).bindparams(bindparam("payload", type_=Jsonb))
        return conn.execute(stmt, {"payload": payload}).rowcount

    def count_by_relation_type(self, conn: Connection) -> list[tuple[str, int]]:
        # Alias `rel_type` / `cnt` : nommer une colonne `t` heurterait l'attribut déprécié `Row.t` de SQLAlchemy (`r.t` renverrait la Row entière, non la colonne).
        rows = conn.execute(
            text(
                "SELECT relation_type::text AS rel_type, count(*) AS cnt FROM publication_relations "
                "GROUP BY relation_type ORDER BY cnt DESC"
            )
        ).all()
        return [(r.rel_type, r.cnt) for r in rows]
