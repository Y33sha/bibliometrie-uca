"""Query service : opérations sur la table `staging`.

Partagé par tous les normalizers (`application/pipeline/normalize/*.py`)
via la classe template `SourceNormalizer`.

La table `staging` stocke les raw_data téléchargées par les extracteurs,
avec un flag `processed` que les normalizers positionnent à TRUE.

Chaque fonction dispatche sur le type du premier argument : curseur
psycopg (mode legacy) ou `Connection` SA Core (mode cible). Le dispatch
disparaîtra quand les 6 normalizers seront migrés en SA.
"""

from typing import Any

from sqlalchemy import Connection, text

from infrastructure.db_helpers import row_val


def reset_processed_flag(conn_or_cur: Any, source: str) -> int:
    """Remet tous les `staging` de la source à `processed=FALSE`. Retourne rowcount."""
    if isinstance(conn_or_cur, Connection):
        return conn_or_cur.execute(
            text("UPDATE staging SET processed = FALSE WHERE source = :source"),
            {"source": source},
        ).rowcount
    conn_or_cur.execute("UPDATE staging SET processed = FALSE WHERE source = %s", (source,))
    return conn_or_cur.rowcount


def count_pending_staging(conn_or_cur: Any, source: str) -> int:
    """Nombre de `staging` avec `processed=FALSE` pour la source donnée."""
    if isinstance(conn_or_cur, Connection):
        row = conn_or_cur.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM staging WHERE source = :source AND processed = FALSE"
            ),
            {"source": source},
        ).one_or_none()
        return row.cnt if row else 0
    conn_or_cur.execute(
        "SELECT COUNT(*) AS cnt FROM staging WHERE source = %s AND processed = FALSE",
        (source,),
    )
    row = conn_or_cur.fetchone()
    if row is None:
        return 0
    return row["cnt"] if isinstance(row, dict) else row[0]


def fetch_pending_staging(conn_or_cur: Any, source: str, *, columns: str, limit: int) -> list[Any]:
    """Charge les `limit` premiers `staging` non traités avec les colonnes demandées.

    `columns` est injecté via f-string pour supporter le select-list sur mesure
    (les normalizers ont chacun leurs colonnes utiles) ; il est contrôlé par
    la classe `SourceNormalizer.FETCH_COLUMNS`, jamais par un input utilisateur.
    """
    if isinstance(conn_or_cur, Connection):
        return list(
            conn_or_cur.execute(
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
    conn_or_cur.execute(
        f"""
        SELECT {columns}
        FROM staging
        WHERE source = %s AND processed = FALSE
        ORDER BY id
        LIMIT %s
        """,
        (source, limit),
    )
    return conn_or_cur.fetchall()


def fetch_pending_staging_ids(conn_or_cur: Any, source: str, *, limit: int) -> list[int]:
    """Charge seulement les `id` des `staging` non traités (pour fetch par sous-lots)."""
    if isinstance(conn_or_cur, Connection):
        rows = conn_or_cur.execute(
            text("""
                SELECT id FROM staging
                WHERE source = :source AND processed = FALSE
                ORDER BY id
                LIMIT :lim
            """),
            {"source": source, "lim": limit},
        ).all()
        return [r.id for r in rows]
    conn_or_cur.execute(
        """
        SELECT id FROM staging
        WHERE source = %s AND processed = FALSE
        ORDER BY id
        LIMIT %s
        """,
        (source, limit),
    )
    return [row_val(r, "id", row_val(r, 0)) for r in conn_or_cur.fetchall()]


def fetch_staging_by_ids(conn_or_cur: Any, staging_ids: list[int], *, columns: str) -> list[Any]:
    """Charge les `staging` dont l'id est dans la liste donnée."""
    if isinstance(conn_or_cur, Connection):
        return list(
            conn_or_cur.execute(
                text(f"""
                    SELECT {columns}
                    FROM staging WHERE id = ANY(:ids)
                    ORDER BY id
                """),
                {"ids": staging_ids},
            ).all()
        )
    conn_or_cur.execute(
        f"""
        SELECT {columns}
        FROM staging WHERE id = ANY(%s)
        ORDER BY id
        """,
        (staging_ids,),
    )
    return conn_or_cur.fetchall()


def mark_done(conn_or_cur: Any, staging_id: int) -> None:
    """Marque un staging comme traité et vide le raw_data."""
    if isinstance(conn_or_cur, Connection):
        conn_or_cur.execute(
            text("UPDATE staging SET processed = TRUE, raw_data = '{}'::jsonb WHERE id = :sid"),
            {"sid": staging_id},
        )
        return
    conn_or_cur.execute(
        "UPDATE staging SET processed = TRUE, raw_data = '{}'::jsonb WHERE id = %s",
        (staging_id,),
    )


class PgStagingQueries:
    """Adapter PostgreSQL pour `application.ports.staging.StagingQueries`."""

    def reset_processed_flag(self, conn_or_cur: Any, source: str) -> int:
        return reset_processed_flag(conn_or_cur, source)

    def count_pending_staging(self, conn_or_cur: Any, source: str) -> int:
        return count_pending_staging(conn_or_cur, source)

    def fetch_pending_staging(
        self, conn_or_cur: Any, source: str, *, columns: str, limit: int
    ) -> list[Any]:
        return fetch_pending_staging(conn_or_cur, source, columns=columns, limit=limit)

    def fetch_pending_staging_ids(self, conn_or_cur: Any, source: str, *, limit: int) -> list[int]:
        return fetch_pending_staging_ids(conn_or_cur, source, limit=limit)

    def fetch_staging_by_ids(
        self, conn_or_cur: Any, staging_ids: list[int], *, columns: str
    ) -> list[Any]:
        return fetch_staging_by_ids(conn_or_cur, staging_ids, columns=columns)

    def mark_done(self, conn_or_cur: Any, staging_id: int) -> None:
        mark_done(conn_or_cur, staging_id)
