"""Query service : opérations sur la table `staging`.

Partagé par tous les normalizers (`application/pipeline/normalize/*.py`)
via la classe template `SourceNormalizer`.

La table `staging` stocke les raw_data téléchargées par les extracteurs,
avec un flag `processed` que les normalizers positionnent à TRUE.
"""

from sqlalchemy import Connection, Row, text

from application.ports.pipeline.staging import (
    HalStagingRow,
    StagingQueries,
    StagingRow,
)

# Colonnes communes (4) ; HAL ajoute `hal_collections`.
_COMMON_COLUMNS = "id, source_id, doi, raw_data"
_HAL_COLUMNS = f"{_COMMON_COLUMNS}, hal_collections"


def _columns_for(source: str) -> str:
    return _HAL_COLUMNS if source == "hal" else _COMMON_COLUMNS


def _row_for(source: str, r: Row) -> StagingRow:  # type: ignore[type-arg]
    """Construit le `StagingRow` (ou `HalStagingRow` pour HAL) depuis une row SA."""
    if source == "hal":
        return HalStagingRow(
            id=r.id,
            source_id=r.source_id,
            doi=r.doi,
            raw_data=r.raw_data,
            hal_collections=r.hal_collections,
        )
    return StagingRow(id=r.id, source_id=r.source_id, doi=r.doi, raw_data=r.raw_data)


def reset_processed_flag(conn: Connection, source: str) -> int:
    """Remet tous les `staging` de la source à `processed=FALSE`. Retourne rowcount."""
    return conn.execute(
        text("UPDATE staging SET processed = FALSE WHERE source = :source"),
        {"source": source},
    ).rowcount


def count_pending_staging(conn: Connection, source: str) -> int:
    """Nombre de `staging` avec `processed=FALSE` pour la source donnée."""
    row = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM staging WHERE source = :source AND processed = FALSE"),
        {"source": source},
    ).one_or_none()
    return row.cnt if row else 0


def fetch_pending_staging(conn: Connection, source: str, *, limit: int) -> list[StagingRow]:
    """Charge les `limit` premiers `staging` non traités pour la source.

    Pour `source == 'hal'`, retourne des `HalStagingRow` (avec `hal_collections`).
    """
    columns = _columns_for(source)
    rows = conn.execute(
        text(f"""
            SELECT {columns}
            FROM staging
            WHERE source = :source AND processed = FALSE
            ORDER BY id
            LIMIT :lim
        """),
        {"source": source, "lim": limit},
    ).all()
    return [_row_for(source, r) for r in rows]


def fetch_pending_staging_ids(conn: Connection, source: str, *, limit: int) -> list[int]:
    """Charge seulement les `id` des `staging` non traités (pour fetch par sous-lots)."""
    rows = conn.execute(
        text("""
            SELECT id FROM staging
            WHERE source = :source AND processed = FALSE
            ORDER BY id
            LIMIT :lim
        """),
        {"source": source, "lim": limit},
    ).all()
    return [r.id for r in rows]


def fetch_staging_by_ids(
    conn: Connection, staging_ids: list[int], *, source: str
) -> list[StagingRow]:
    """Charge les `staging` dont l'id est dans la liste donnée.

    `source` détermine la projection : `'hal'` ajoute la colonne `hal_collections`
    et construit des `HalStagingRow` (les ids fournis doivent appartenir à cette source).
    """
    columns = _columns_for(source)
    rows = conn.execute(
        text(f"""
            SELECT {columns}
            FROM staging WHERE id = ANY(:ids)
            ORDER BY id
        """),
        {"ids": staging_ids},
    ).all()
    return [_row_for(source, r) for r in rows]


def mark_done(conn: Connection, staging_id: int) -> None:
    """Marque un staging comme traité et vide le raw_data."""
    conn.execute(
        text("UPDATE staging SET processed = TRUE, raw_data = '{}'::jsonb WHERE id = :sid"),
        {"sid": staging_id},
    )


class PgStagingQueries(StagingQueries):
    """Adapter PostgreSQL pour `application.ports.staging.StagingQueries`."""

    def reset_processed_flag(self, conn: Connection, source: str) -> int:
        return reset_processed_flag(conn, source)

    def count_pending_staging(self, conn: Connection, source: str) -> int:
        return count_pending_staging(conn, source)

    def fetch_pending_staging(
        self, conn: Connection, source: str, *, limit: int
    ) -> list[StagingRow]:
        return fetch_pending_staging(conn, source, limit=limit)

    def fetch_pending_staging_ids(self, conn: Connection, source: str, *, limit: int) -> list[int]:
        return fetch_pending_staging_ids(conn, source, limit=limit)

    def fetch_staging_by_ids(
        self, conn: Connection, staging_ids: list[int], *, source: str
    ) -> list[StagingRow]:
        return fetch_staging_by_ids(conn, staging_ids, source=source)

    def mark_done(self, conn: Connection, staging_id: int) -> None:
        mark_done(conn, staging_id)
