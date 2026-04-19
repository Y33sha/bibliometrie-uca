"""Query service : opérations sur la table `staging`.

Partagé par tous les normaliseurs (`application/pipeline/normalize/*.py`)
via la classe template `SourceNormalizer`.

La table `staging` stocke les raw_data téléchargées par les extracteurs,
avec un flag `processed` que les normaliseurs positionnent à TRUE.
"""

from typing import Any

from infrastructure.db_helpers import row_val


def reset_processed_flag(cur: Any, source: str) -> int:
    """Remet tous les `staging` de la source à `processed=FALSE`. Retourne rowcount."""
    cur.execute("UPDATE staging SET processed = FALSE WHERE source = %s", (source,))
    return cur.rowcount


def count_pending_staging(cur: Any, source: str) -> int:
    """Nombre de `staging` avec `processed=FALSE` pour la source donnée."""
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM staging WHERE source = %s AND processed = FALSE",
        (source,),
    )
    row = cur.fetchone()
    if row is None:
        return 0
    return row["cnt"] if isinstance(row, dict) else row[0]


def fetch_pending_staging(cur: Any, source: str, *, columns: str, limit: int) -> list[Any]:
    """Charge les `limit` premiers `staging` non traités avec les colonnes demandées.

    `columns` est injecté via f-string pour supporter le select-list sur mesure
    (les normaliseurs ont chacun leurs colonnes utiles) ; il est contrôlé par
    la classe `SourceNormalizer.FETCH_COLUMNS`, jamais par un input utilisateur.
    """
    cur.execute(
        f"""
        SELECT {columns}
        FROM staging
        WHERE source = %s AND processed = FALSE
        ORDER BY id
        LIMIT %s
        """,
        (source, limit),
    )
    return cur.fetchall()


def fetch_pending_staging_ids(cur: Any, source: str, *, limit: int) -> list[int]:
    """Charge seulement les `id` des `staging` non traités (pour fetch par sous-lots)."""
    cur.execute(
        """
        SELECT id FROM staging
        WHERE source = %s AND processed = FALSE
        ORDER BY id
        LIMIT %s
        """,
        (source, limit),
    )
    return [row_val(r, "id", row_val(r, 0)) for r in cur.fetchall()]


def fetch_staging_by_ids(cur: Any, staging_ids: list[int], *, columns: str) -> list[Any]:
    """Charge les `staging` dont l'id est dans la liste donnée."""
    cur.execute(
        f"""
        SELECT {columns}
        FROM staging WHERE id = ANY(%s)
        ORDER BY id
        """,
        (staging_ids,),
    )
    return cur.fetchall()


class PgStagingQueries:
    """Adapter PostgreSQL pour `application.ports.staging.StagingQueries`."""

    def reset_processed_flag(self, cur: Any, source: str) -> int:
        return reset_processed_flag(cur, source)

    def count_pending_staging(self, cur: Any, source: str) -> int:
        return count_pending_staging(cur, source)

    def fetch_pending_staging(
        self, cur: Any, source: str, *, columns: str, limit: int
    ) -> list[Any]:
        return fetch_pending_staging(cur, source, columns=columns, limit=limit)

    def fetch_pending_staging_ids(self, cur: Any, source: str, *, limit: int) -> list[int]:
        return fetch_pending_staging_ids(cur, source, limit=limit)

    def fetch_staging_by_ids(self, cur: Any, staging_ids: list[int], *, columns: str) -> list[Any]:
        return fetch_staging_by_ids(cur, staging_ids, columns=columns)
