"""Query service : opérations sur la table `staging`.

Partagé par tous les normalizers (`application/pipeline/normalize/*.py`) via la classe template `SourceNormalizer`.

La table `staging` stocke les raw_data téléchargées par les extracteurs, avec un flag `processed` que les normalizers positionnent à TRUE.
"""

import logging
from collections.abc import Mapping

from sqlalchemy import Connection, Row, bindparam, text

from application.ports.pipeline.normalize.staging import (
    StagingQueries,
    StagingRow,
)
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.pipeline.change_detection import canonical_json_bytes, change_detection_hash
from infrastructure.raw_store import RawStore, get_raw_store

logger = logging.getLogger(__name__)

_COLUMNS = "id, source_id, doi, raw_data"


def _row(r: Row) -> StagingRow:  # type: ignore[type-arg]
    """Construit le `StagingRow` depuis une ligne SQL."""
    return StagingRow(id=r.id, source_id=r.source_id, doi=r.doi, raw_data=r.raw_data)


_MARK_DONE_SQL = text(
    """
    UPDATE staging s
    SET processed = TRUE, raw_data = '{}'::jsonb
    FROM (
        SELECT id, source::text AS source, source_id, raw_data
        FROM staging WHERE id = :sid
    ) old
    WHERE s.id = old.id
    RETURNING old.source AS source, old.source_id AS source_id, old.raw_data AS raw_data
    """
)


def fetch_existing_source_ids(conn: Connection, source: str) -> set[str]:
    """Set des `source_id` déjà présents en staging pour une source."""
    rows = conn.execute(
        text("SELECT source_id FROM staging WHERE source = :source"),
        {"source": source},
    ).scalars()
    return set(rows)


# ── Réhydratation depuis le raw store (inverse de mark_done) ────

_REHYDRATE_UPDATE_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, raw_hash = :raw_hash, processed = FALSE
    WHERE source = :source AND source_id = :source_id
    """
).bindparams(bindparam("raw_data", type_=Jsonb))

_REHYDRATE_UPSERT_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES (:source, :source_id, :doi, :raw_data, :raw_hash, FALSE)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = EXCLUDED.raw_data,
        raw_hash = EXCLUDED.raw_hash,
        processed = FALSE
    RETURNING (xmax = 0) AS inserted
    """
).bindparams(bindparam("raw_data", type_=Jsonb))


def rehydrate_staging_row(
    conn: Connection, source: str, source_id: str, raw_data: Mapping[str, JsonValue]
) -> bool:
    """Réinjecte un payload archivé dans une ligne `staging` existante, prête à renormaliser.

    Inverse de `mark_done` : repose `raw_data`, recalcule `raw_hash` (`change_detection_hash`, même empreinte que l'UPSERT d'extraction, pour qu'une ligne réhydratée ne re-diverge pas au moissonnage suivant) et remet `processed = FALSE`. Ne touche que les lignes déjà présentes : retourne `False` si `(source, source_id)` est absent (clé orpheline au raw store).
    """
    return (
        conn.execute(
            _REHYDRATE_UPDATE_SQL,
            {
                "raw_data": raw_data,
                "raw_hash": change_detection_hash(source, raw_data),
                "source": source,
                "source_id": source_id,
            },
        ).rowcount
        > 0
    )


def rehydrate_or_create_staging_row(
    conn: Connection,
    source: str,
    source_id: str,
    doi: str | None,
    raw_data: Mapping[str, JsonValue],
) -> bool:
    """Réhydrate une ligne `staging`, en la créant si elle manque (après un `TRUNCATE staging`, où tout est orphelin).

    Upsert : réinsère les clés orphelines et écrase inconditionnellement les existantes. `doi` n'est posé qu'à l'insertion — une ligne préexistante garde son `doi` d'origine. Retourne `True` si la ligne vient d'être insérée, `False` si elle existait et a été mise à jour.
    """
    return bool(
        conn.execute(
            _REHYDRATE_UPSERT_SQL,
            {
                "raw_data": raw_data,
                "raw_hash": change_detection_hash(source, raw_data),
                "source": source,
                "source_id": source_id,
                "doi": doi,
            },
        ).scalar_one()
    )


class PgStagingQueries(StagingQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.normalize.staging.StagingQueries`.

    `raw_store` (défaut : `get_raw_store()`) reçoit chaque payload `raw_data` juste avant sa vidange par `mark_done` (archivage hors BDD). Injectable pour les tests.
    """

    def __init__(self, raw_store: RawStore | None = None) -> None:
        self._raw_store = raw_store if raw_store is not None else get_raw_store()

    def count_pending_staging(self, conn: Connection, source: str) -> int:
        row = conn.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM staging WHERE source = :source AND processed = FALSE"
            ),
            {"source": source},
        ).one_or_none()
        return row.cnt if row else 0

    def fetch_pending_staging(
        self, conn: Connection, source: str, *, limit: int
    ) -> list[StagingRow]:
        rows = conn.execute(
            text(f"""
                SELECT {_COLUMNS}
                FROM staging
                WHERE source = :source AND processed = FALSE
                ORDER BY id
                LIMIT :lim
            """),
            {"source": source, "lim": limit},
        ).all()
        return [_row(r) for r in rows]

    def fetch_pending_staging_ids(self, conn: Connection, source: str) -> list[int]:
        rows = conn.execute(
            text("""
                SELECT id FROM staging
                WHERE source = :source AND processed = FALSE
                ORDER BY id
            """),
            {"source": source},
        ).all()
        return [r.id for r in rows]

    def fetch_staging_by_ids(self, conn: Connection, staging_ids: list[int]) -> list[StagingRow]:
        rows = conn.execute(
            text(f"""
                SELECT {_COLUMNS}
                FROM staging WHERE id = ANY(:ids)
                ORDER BY id
            """),
            {"ids": staging_ids},
        ).all()
        return [_row(r) for r in rows]

    def mark_done(self, conn: Connection, staging_id: int) -> None:
        # `old` capture le payload avant vidange ; l'archivage au raw store est best-effort (un échec ne casse pas la normalisation, la base reste la source de vérité).
        row = conn.execute(_MARK_DONE_SQL, {"sid": staging_id}).one_or_none()
        if row is None or not row.raw_data:  # `{}` (stub not-found) → rien à archiver
            return
        try:
            self._raw_store.put(row.source, row.source_id, canonical_json_bytes(row.raw_data))
        except Exception:
            logger.warning(
                "raw_store.put a échoué pour %s/%s (payload non archivé)",
                row.source,
                row.source_id,
                exc_info=True,
            )
