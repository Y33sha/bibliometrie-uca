"""Query service : SQL de la passe de réconciliation des composantes.

Implémente `application.ports.pipeline.publications_reconciliation.PublicationsReconciliationQueries`.
"""

from sqlalchemy import Connection, bindparam, text

from application.ports.pipeline.publications_reconciliation import (
    PublicationsReconciliationQueries,
    ReconcileRow,
)
from domain.source_publications.keys import METADATA_BLOCK_MIN_TITLE_LENGTH


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
    -- DOI : égalité directe (la colonne est toujours normalisée minuscule par `clean_doi` à
    -- l'écriture), pour utiliser l'index btree `idx_source_pubs_doi` plutôt qu'un scan via `lower()`.
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o ON o.doi IS NOT NULL AND o.doi = d.doi
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
    -- Token metadata_block : même doc_type + titre + année, pour tout doc_type, titre assez long.
    SELECT {_COLS.format(a="o")}
    FROM dirty d
    JOIN source_publications o
      ON o.doc_type = d.doc_type
         AND o.title_normalized = d.title_normalized
         AND o.pub_year = d.pub_year
    LEFT JOIN publications p ON p.id = o.publication_id
    WHERE d.doc_type IS NOT NULL
      AND length(d.title_normalized) > {METADATA_BLOCK_MIN_TITLE_LENGTH}
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


def fetch_publication_ids_by_doi(conn: Connection) -> dict[str, int]:
    # Map `lower(doi) → id` des publications portant un DOI. Clé sur `lower(doi)` :
    # l'index unique `publications_doi_lower_key` garantit l'unicité, et le DOI de
    # partition (`effective_doi`, via `clean_doi`) est déjà en minuscule.
    rows = conn.execute(
        text("SELECT id, lower(doi) AS doi FROM publications WHERE doi IS NOT NULL")
    ).all()
    return {row.doi: row.id for row in rows}


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


def mark_keys_dirty(conn: Connection, where: str | None = None, *, dry_run: bool = False) -> int:
    """Pose `keys_dirty = true` sur les source_publications — toutes, ou le sous-ensemble `where`.

    Outil de re-matérialisation : quand une règle de clés de confirmation change (nouveau token,
    seuil de garde modifié, projection revue), le stock déjà réconcilié ne reflète plus la règle.
    Re-marquer `keys_dirty` fait re-réconcilier les SP concernées au prochain run de la phase
    `publications` ; sur tout le stock, c'est le *cluster-then-materialize* global. `where` est un
    **fragment SQL de confiance** (CLI maintenance / run_pipeline, jamais une entrée externe).
    `dry_run` compte sans écrire. Retourne le nombre de SP (marquées, ou qui le seraient).
    """
    clause = f" WHERE {where}" if where else ""
    if dry_run:
        return conn.execute(
            text(f"SELECT count(*) FROM source_publications{clause}")  # noqa: S608
        ).scalar_one()
    return conn.execute(
        text(f"UPDATE source_publications SET keys_dirty = true{clause}")  # noqa: S608
    ).rowcount


def count_publications(conn: Connection) -> int:
    # Toutes les publications sont in-périmètre par construction : la réconciliation gate leur création sur le périmètre.
    return int(conn.execute(text("SELECT count(*) FROM publications")).scalar_one())


class PgPublicationsReconciliationQueries(PublicationsReconciliationQueries):
    """Adapter PostgreSQL pour `PublicationsReconciliationQueries`."""

    def mark_keys_dirty(self, conn: Connection) -> int:
        return mark_keys_dirty(conn)

    def fetch_dirty_source_publication_ids(self, conn: Connection) -> list[int]:
        return fetch_dirty_source_publication_ids(conn)

    def fetch_reconciliation_universe(self, conn: Connection) -> list[ReconcileRow]:
        return fetch_reconciliation_universe(conn)

    def fetch_publication_ids_by_doi(self, conn: Connection) -> dict[str, int]:
        return fetch_publication_ids_by_doi(conn)

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

    def count_publications(self, conn: Connection) -> int:
        return count_publications(conn)
