"""Query service : SQL de la passe de réconciliation des composantes.

Implémente `application.ports.pipeline.publications_reconciliation.PublicationsReconciliationQueries`.
"""

from sqlalchemy import Connection, bindparam, text

from application.ports.pipeline.publications_reconciliation import (
    PublicationsReconciliationQueries,
    ReconcileRow,
)


def fetch_dirty_source_publication_ids(conn: Connection) -> list[int]:
    rows = conn.execute(
        text("""
            SELECT id FROM source_publications
            WHERE keys_dirty AND publication_id IS NOT NULL
            ORDER BY id
        """)
    ).all()
    return [row.id for row in rows]


# Voisinage 1-hop : les SP dirty (avec publication) + celles qui partagent une clé de
# confirmation avec elles. Une branche UNION par type de clé ; `UNION` dédoublonne.
# Dernière branche = composite thèse (doc_type thèse + title_normalized + pub_year),
# le token métadonnée : sans elle, la SP voisine ne serait pas ramenée et l'arête
# thèse serait invisible à `connected_components`.
# (Au full rerun tout est dirty : l'univers = tout le stock matérialisé = reclustering global.)
_RECON_COLS = "id, doi, external_ids, publication_id, doc_type, title_normalized, pub_year"
_UNIVERSE_SQL = text(f"""
    WITH dirty AS (
        SELECT {_RECON_COLS}
        FROM source_publications
        WHERE keys_dirty AND publication_id IS NOT NULL
    )
    SELECT {_RECON_COLS} FROM dirty
    UNION
    SELECT {", ".join("o." + c for c in _RECON_COLS.split(", "))}
    FROM dirty d
    JOIN source_publications o
      ON o.publication_id IS NOT NULL AND o.doi IS NOT NULL AND lower(o.doi) = lower(d.doi)
    WHERE d.doi IS NOT NULL
    UNION
    SELECT {", ".join("o." + c for c in _RECON_COLS.split(", "))}
    FROM dirty d
    JOIN source_publications o
      ON o.publication_id IS NOT NULL
         AND o.external_ids ->> 'nnt' = d.external_ids ->> 'nnt'
    WHERE d.external_ids ? 'nnt'
    UNION
    SELECT {", ".join("o." + c for c in _RECON_COLS.split(", "))}
    FROM dirty d
    JOIN source_publications o
      ON o.publication_id IS NOT NULL
         AND o.external_ids ->> 'pmid' = d.external_ids ->> 'pmid'
    WHERE d.external_ids ? 'pmid'
    UNION
    SELECT {", ".join("o." + c for c in _RECON_COLS.split(", "))}
    FROM dirty d
    CROSS JOIN LATERAL jsonb_array_elements_text(d.external_ids -> 'hal_id') AS dh(hal)
    JOIN source_publications o
      ON o.publication_id IS NOT NULL
         AND o.external_ids -> 'hal_id' @> jsonb_build_array(dh.hal)
    WHERE jsonb_typeof(d.external_ids -> 'hal_id') = 'array'
    UNION
    SELECT {", ".join("o." + c for c in _RECON_COLS.split(", "))}
    FROM dirty d
    JOIN source_publications o
      ON o.publication_id IS NOT NULL
         AND o.doc_type IN ('thesis', 'ongoing_thesis')
         AND o.title_normalized = d.title_normalized
         AND o.pub_year = d.pub_year
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
        )
        for r in rows
    ]


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

    def clear_keys_dirty(self, conn: Connection, source_publication_ids: list[int]) -> int:
        return clear_keys_dirty(conn, source_publication_ids)
