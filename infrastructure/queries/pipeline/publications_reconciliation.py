"""Query service : SQL de la passe de réconciliation des composantes.

Implémente `application.ports.pipeline.publications_reconciliation.PublicationsReconciliationQueries`.
"""

from sqlalchemy import Connection, bindparam, text

from application.ports.pipeline.publications_reconciliation import (
    PublicationsReconciliationQueries,
    ReconcileRow,
)


def fetch_dirty_source_publication_ids(conn: Connection) -> list[int]:
    # Orphelins **compris** : la réconciliation est aussi l'assignation (un orphelin dirty
    # se fait matcher/créer/skipper). Les SP traitées sont ensuite nettoyées (`clear_keys_dirty`).
    rows = conn.execute(
        text("SELECT id FROM source_publications WHERE keys_dirty ORDER BY id")
    ).all()
    return [row.id for row in rows]


# Voisinage 1-hop : les SP dirty (orphelines comprises) + celles qui partagent une clé de
# confirmation avec elles (matérialisées **ou** orphelines). Une branche UNION par type de
# clé ; `UNION` dédoublonne. Dernière branche = composite thèse (le token métadonnée).
# `publication_doi` (via LEFT JOIN, `NULL` pour les orphelines) sert à choisir l'ancre ;
# `in_perimeter` (EXISTS) gate la création d'une pub neuve pour une partition d'orphelins.
# (Au full rerun tout est dirty : l'univers = tout le stock = cluster-then-materialize global.)
_COLS = (
    "{a}.id, {a}.doi, {a}.external_ids, {a}.publication_id, "
    "{a}.doc_type, {a}.title_normalized, {a}.pub_year, p.doi AS publication_doi, "
    "EXISTS (SELECT 1 FROM source_authorships sa "
    "WHERE sa.source_publication_id = {a}.id AND sa.in_perimeter) AS in_perimeter"
)
_UNIVERSE_SQL = text(f"""
    WITH dirty AS (
        SELECT {_COLS.format(a="sd")}
        FROM source_publications sd
        LEFT JOIN publications p ON p.id = sd.publication_id
        WHERE sd.keys_dirty
    )
    SELECT id, doi, external_ids, publication_id, doc_type, title_normalized, pub_year,
           publication_doi, in_perimeter
    FROM dirty
    UNION
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o ON o.doi IS NOT NULL AND lower(o.doi) = lower(d.doi)
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.doi IS NOT NULL
    UNION
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o ON o.external_ids ->> 'nnt' = d.external_ids ->> 'nnt'
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.external_ids ? 'nnt'
    UNION
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o ON o.external_ids ->> 'pmid' = d.external_ids ->> 'pmid'
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.external_ids ? 'pmid'
    UNION
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    CROSS JOIN LATERAL jsonb_array_elements_text(d.external_ids -> 'hal_id') AS dh(hal)
    JOIN source_publications o ON o.external_ids -> 'hal_id' @> jsonb_build_array(dh.hal)
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE jsonb_typeof(d.external_ids -> 'hal_id') = 'array'
    UNION
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o
      ON o.doc_type IN ('thesis', 'ongoing_thesis')
         AND o.title_normalized = d.title_normalized
         AND o.pub_year = d.pub_year
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.doc_type IN ('thesis', 'ongoing_thesis')
      AND COALESCE(d.title_normalized, '') <> ''
      AND d.pub_year IS NOT NULL
""")


def fetch_reconciliation_universe(conn: Connection) -> list[ReconcileRow]:
    rows = conn.execute(_UNIVERSE_SQL).all()
    return [
        ReconcileRow(
            r.id,
            r.doi,
            r.external_ids,
            r.publication_id,
            r.doc_type,
            r.title_normalized,
            r.pub_year,
            r.publication_doi,
            r.in_perimeter,
        )
        for r in rows
    ]


def repoint_source_publications(
    conn: Connection, source_publication_ids: list[int], publication_id: int
) -> None:
    if not source_publication_ids:
        return
    stmt = text(
        "UPDATE source_publications SET publication_id = :pid WHERE id = ANY(:ids)"
    ).bindparams(bindparam("ids"))
    conn.execute(stmt, {"pid": publication_id, "ids": source_publication_ids})


def repoint_dependents(conn: Connection, from_publication_id: int, to_publication_id: int) -> None:
    # distinct_publications : re-pointer chaque paire (from, autre) en (autre, to) réordonnée,
    # écarter l'auto-paire, dédupliquer, puis supprimer les paires de `from`.
    conn.execute(
        text("""
            INSERT INTO distinct_publications (pub_id_a, pub_id_b)
            SELECT LEAST(other_id, :t), GREATEST(other_id, :t)
            FROM (
                SELECT CASE WHEN pub_id_a = :s THEN pub_id_b ELSE pub_id_a END AS other_id
                FROM distinct_publications
                WHERE pub_id_a = :s OR pub_id_b = :s
            ) pairs
            WHERE other_id <> :t
            ON CONFLICT (pub_id_a, pub_id_b) DO NOTHING
        """),
        {"s": from_publication_id, "t": to_publication_id},
    )
    conn.execute(
        text("DELETE FROM distinct_publications WHERE pub_id_a = :s OR pub_id_b = :s"),
        {"s": from_publication_id},
    )
    conn.execute(
        text("UPDATE apc_payments SET publication_id = :t WHERE publication_id = :s"),
        {"s": from_publication_id, "t": to_publication_id},
    )


def clear_keys_dirty(conn: Connection, source_publication_ids: list[int]) -> int:
    if not source_publication_ids:
        return 0
    stmt = text(
        "UPDATE source_publications SET keys_dirty = false WHERE id = ANY(:ids)"
    ).bindparams(bindparam("ids"))
    return conn.execute(stmt, {"ids": source_publication_ids}).rowcount


class PgPublicationsReconciliationQueries(PublicationsReconciliationQueries):
    """Adapter PostgreSQL pour `PublicationsReconciliationQueries`."""

    def fetch_dirty_source_publication_ids(self, conn: Connection) -> list[int]:
        return fetch_dirty_source_publication_ids(conn)

    def fetch_reconciliation_universe(self, conn: Connection) -> list[ReconcileRow]:
        return fetch_reconciliation_universe(conn)

    def repoint_source_publications(
        self, conn: Connection, source_publication_ids: list[int], publication_id: int
    ) -> None:
        repoint_source_publications(conn, source_publication_ids, publication_id)

    def repoint_dependents(
        self, conn: Connection, from_publication_id: int, to_publication_id: int
    ) -> None:
        repoint_dependents(conn, from_publication_id, to_publication_id)

    def clear_keys_dirty(self, conn: Connection, source_publication_ids: list[int]) -> int:
        return clear_keys_dirty(conn, source_publication_ids)
