"""Query service : opérations sur la table `staging`.

Partagé par tous les normalizers (`application/pipeline/normalize/*.py`)
via la classe template `SourceNormalizer`.

La table `staging` stocke les raw_data téléchargées par les extracteurs,
avec un flag `processed` que les normalizers positionnent à TRUE.
"""

from typing import Any

from sqlalchemy import Connection, text


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


def fetch_pending_staging(conn: Connection, source: str, *, columns: str, limit: int) -> list[Any]:
    """Charge les `limit` premiers `staging` non traités avec les colonnes demandées.

    `columns` est injecté via f-string pour supporter le select-list sur mesure
    (les normalizers ont chacun leurs colonnes utiles) ; il est contrôlé par
    la classe `SourceNormalizer.FETCH_COLUMNS`, jamais par un input utilisateur.

    Retourne une liste de SA `Row` : accès par attribut (`row.id`, `row.raw_data`)
    ou par position (`row[0]`).
    """
    return list(
        conn.execute(
            text(f"""
                SELECT {columns}
                FROM staging
                WHERE source = :source AND processed = FALSE
                ORDER BY id
                LIMIT :lim
            """),
            {"source": source, "lim": limit},
        ).all()
    )


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


def fetch_staging_by_ids(conn: Connection, staging_ids: list[int], *, columns: str) -> list[Any]:
    """Charge les `staging` dont l'id est dans la liste donnée."""
    return list(
        conn.execute(
            text(f"""
                SELECT {columns}
                FROM staging WHERE id = ANY(:ids)
                ORDER BY id
            """),
            {"ids": staging_ids},
        ).all()
    )


def mark_done(conn: Connection, staging_id: int) -> None:
    """Marque un staging comme traité et vide le raw_data."""
    conn.execute(
        text("UPDATE staging SET processed = TRUE, raw_data = '{}'::jsonb WHERE id = :sid"),
        {"sid": staging_id},
    )


class PgStagingQueries:
    """Adapter PostgreSQL pour `application.ports.staging.StagingQueries`."""

    def reset_processed_flag(self, conn: Connection, source: str) -> int:
        return reset_processed_flag(conn, source)

    def count_pending_staging(self, conn: Connection, source: str) -> int:
        return count_pending_staging(conn, source)

    def fetch_pending_staging(
        self, conn: Connection, source: str, *, columns: str, limit: int
    ) -> list[Any]:
        return fetch_pending_staging(conn, source, columns=columns, limit=limit)

    def fetch_pending_staging_ids(self, conn: Connection, source: str, *, limit: int) -> list[int]:
        return fetch_pending_staging_ids(conn, source, limit=limit)

    def fetch_staging_by_ids(
        self, conn: Connection, staging_ids: list[int], *, columns: str
    ) -> list[Any]:
        return fetch_staging_by_ids(conn, staging_ids, columns=columns)

    def mark_done(self, conn: Connection, staging_id: int) -> None:
        mark_done(conn, staging_id)
