"""Table `staging` : écriture des documents rendus par les sources, lecture et marquage par la normalisation.

- `upsert_staging` écrit un document, pour toutes les voies d'entrée (phases `extract`, `fetch_missing` et `fetch_stale`).
- `StagingQueries` lit les lignes à normaliser et marque les lignes traitées, en archivant leur payload au raw store.
- `delete_disappeared_source_publications` retire les notices des documents disparus de leur source ; `rehydrate_*` réinjecte un payload archivé.

Le commit est à la charge de l'appelant.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Connection, Row, ScalarResult, bindparam, text

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.fingerprint import stable_json_bytes
from infrastructure.raw_store import RawStore, get_raw_store
from pipeline.sources.change_detection import change_detection_hash

_logger = logging.getLogger(__name__)

_UPSERT_STAGING_SQL = text(
    """
    WITH old AS (
        SELECT raw_hash AS old_hash FROM staging
        WHERE source = :source AND source_id = :source_id
    )
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, authors_truncated, entry_mode)
    VALUES (:source, :source_id, :doi, :raw_data, :raw_hash, :authors_truncated, :entry_mode)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.raw_data
            ELSE staging.raw_data
        END,
        raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
        -- Renseigne le DOI quand la ligne existait sans (doc moissonné avant que la source ne porte le DOI) ; ne clobbe jamais un DOI déjà posé.
        doi = COALESCE(staging.doi, EXCLUDED.doi),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE
            ELSE staging.processed
        END,
        -- Suit `raw_hash` comme `processed` : un payload bulk inchangé n'écrase pas le flag (préserve l'effacement posé par fetch_truncated) ; un payload modifié le recalcule depuis le nouveau contenu.
        authors_truncated = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.authors_truncated
            ELSE staging.authors_truncated
        END,
        -- `entry_mode` n'est PAS réécrit : il garde la provenance de première création.
        -- Un document rendu par sa source efface le marqueur de disparition.
        disappeared_at = NULL,
        last_seen_at = now()
    RETURNING (xmax = 0) AS inserted,
              ((SELECT old_hash FROM old) IS DISTINCT FROM :raw_hash) AS changed
    """
).bindparams(bindparam("raw_data", type_=Jsonb))


def upsert_staging(
    conn: Connection,
    *,
    source: str,
    source_id: str,
    doi: str | None,
    raw_data: Mapping[str, JsonValue],
    authors_truncated: bool = False,
    entry_mode: str = "bulk",
) -> tuple[bool, bool]:
    """UPSERT d'une ligne `staging`, commun à toutes les voies d'entrée : extraction, phases `fetch_missing` et `fetch_stale`.

    `INSERT … ON CONFLICT (source, source_id) DO UPDATE` piloté par `raw_hash` : réécrit `raw_data` (et repasse `processed=FALSE`) seulement si le hash a changé, met toujours à jour `last_seen_at`, et renseigne `doi` s'il manquait (jamais d'écrasement). Un `raw_hash=null` en base force le re-import (`NULL IS DISTINCT FROM <hash>`). Le hash est calculé via `change_detection_hash`, qui neutralise le bruit volatil propre à la source avant l'empreinte (le payload stocké reste, lui, fidèle).

    `authors_truncated` (OpenAlex : payload bulk plafonné à 100 auteurs) suit la même logique que `processed` — (re)posé seulement quand le hash change, sinon préservé (n'écrase pas l'effacement de `fetch_truncated`). Les sources non plafonnées laissent le défaut `False`.

    `entry_mode` enregistre comment la ligne est **entrée** : `bulk` à l'extraction, `fetch_missing_doi` ou `fetch_missing_hal` à la phase `fetch_missing`, `manual_export` à l'import d'un export de l'interface d'une source. Posé à la création, jamais réécrit.

    Retourne `(inserted, changed)` : `inserted` = vraie insertion (`xmax = 0`), `changed` = contenu réécrit (hash distinct de celui déjà en base). Le commit est à la charge de l'appelant.
    """
    row = conn.execute(
        _UPSERT_STAGING_SQL,
        {
            "source": source,
            "source_id": source_id,
            "doi": clean_doi(doi),
            "raw_data": raw_data,
            "raw_hash": change_detection_hash(source, raw_data),
            "authors_truncated": authors_truncated,
            "entry_mode": entry_mode,
        },
    ).one()
    return (bool(row.inserted), bool(row.changed))


class UpsertOutcome(StrEnum):
    """Issue de l'UPSERT d'une ligne `staging` unique, dérivée des signaux `(inserted, changed)` du helper canonique.

    - `NEW` : vraie insertion (`RETURNING (xmax = 0)`).
    - `UPDATED` : ligne existante dont le **contenu a changé** (`raw_data` réécrit, `raw_hash` distinct de celui en base).
    - `UNCHANGED` : ligne re-vue à contenu identique (seul `last_seen_at` bumpé).
    """

    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"

    @classmethod
    def of(cls, *, inserted: bool, changed: bool) -> UpsertOutcome:
        """Classe le résultat d'`upsert_staging` : `inserted` prime, le `changed` d'une insertion étant sans objet."""
        if inserted:
            return cls.NEW
        return cls.UPDATED if changed else cls.UNCHANGED


@dataclass(frozen=True)
class BatchInsertCounts:
    """Résultat d'un `insert_batch`, ventilé en trois.

    - `new` : vraie insertion (`RETURNING (xmax = 0)`).
    - `updated` : row existante dont le **contenu a changé** (`raw_data` réécrit, `raw_hash` distinct de l'ancien — capté via une CTE qui lit l'ancien hash avant l'UPSERT, comparé au nouveau dans le `RETURNING`).
    - `unchanged` : row re-vue à contenu identique (seul `last_seen_at` bumpé).
    """

    new: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.new + self.updated + self.unchanged


# ── Normalisation ─────────────────────────────────────────────


@dataclass(frozen=True)
class StagingRow:
    """Ligne de `staging` à normaliser."""

    id: int
    source_id: str
    doi: str | None
    raw_data: Mapping[str, JsonValue]


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
    rows: ScalarResult[str] = conn.execute(
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


class StagingQueries:
    """Lectures et marquages de `staging` par la normalisation.

    `raw_store` (défaut : `get_raw_store()`) reçoit chaque payload `raw_data` juste avant sa vidange par `mark_done` (archivage hors base).
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

    def discard_source_publication(self, conn: Connection, staging_id: int) -> None:
        _delete_source_publications(conn, "s.id = :staging_id", {"staging_id": staging_id})

    def mark_done(self, conn: Connection, staging_id: int) -> None:
        # `old` capture le payload avant vidange ; l'archivage au raw store est best-effort (un échec ne casse pas la normalisation, la base reste la source de vérité).
        row = conn.execute(_MARK_DONE_SQL, {"sid": staging_id}).one_or_none()
        if row is None or not row.raw_data:  # `{}` (stub not-found) → rien à archiver
            return
        try:
            self._raw_store.put(row.source, row.source_id, stable_json_bytes(row.raw_data))
        except Exception:
            _logger.warning(
                "raw_store.put a échoué pour %s/%s (payload non archivé)",
                row.source,
                row.source_id,
                exc_info=True,
            )


def _delete_source_publications(
    conn: Connection, staging_filter: str, params: dict[str, object]
) -> int:
    """Supprime les `source_publications` dont la ligne de `staging` (alias `s`) satisfait `staging_filter`.

    Les `source_publications` rattachées à la même publication sont d'abord marquées `keys_dirty` : la phase `publications` réconcilie alors la publication et recalcule ses métadonnées sans la source retirée. Une publication vidée de toutes ses sources est supprimée en fin de phase `publications`. Les `source_authorships` suivent par cascade. Rend le nombre de `source_publications` supprimées.
    """
    # noqa S608 : `staging_filter` est une constante de ce module, jamais une entrée.
    conn.execute(
        text(f"""
            UPDATE source_publications soeur
            SET keys_dirty = true
            FROM source_publications sp
            JOIN staging s ON s.id = sp.staging_id
            WHERE {staging_filter}
              AND soeur.publication_id = sp.publication_id
              AND soeur.id <> sp.id
              AND NOT soeur.keys_dirty
        """),  # noqa: S608
        params,
    )
    return conn.execute(
        text(f"""
            DELETE FROM source_publications sp
            USING staging s
            WHERE sp.staging_id = s.id AND {staging_filter}
        """),  # noqa: S608
        params,
    ).rowcount


def delete_disappeared_source_publications(conn: Connection) -> int:
    """Supprime les `source_publications` dont le staging porte `disappeared_at` (cf. `_delete_source_publications`). La ligne de `staging` reste, avec sa marque.

    Balayage ensembliste, idempotent.
    """
    return _delete_source_publications(conn, "s.disappeared_at IS NOT NULL", {})
