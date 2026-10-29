"""Table `staging` : écriture des documents rendus par les sources, lecture et marquage par la normalisation.

`StagingStore` écrit un document pour toutes les voies d'entrée (moissonnages, phases `fetch_missing`, `fetch_stale` et `fetch_truncated`, imports), lit les lignes à normaliser et marque les lignes traitées, en archivant leur payload au raw store.

Le commit est à la charge de l'appelant.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Connection, bindparam, text

from domain.publications.identifiers import clean_doi
from domain.sources.registry import DOI_ORG, PROFILES, Source
from domain.sources.staging import StagingEntryMode
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.rows import rows_as
from infrastructure.raw_store import RawStore, get_raw_store
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.change_detection import change_detection_hash
from pipeline.ingestion.common.failed_lookups import (
    forget_failed_doi_lookups,
    forget_failed_hal_id_lookup,
)
from pipeline.ingestion.common.fingerprint import stable_json_bytes
from pipeline.ingestion.common.source_records import delete_source_record_of_staging

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
        -- Renseigne le DOI d'une ligne qui en est dépourvue ; un DOI déjà posé reste.
        doi = COALESCE(staging.doi, EXCLUDED.doi),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE
            ELSE staging.processed
        END,
        -- Suit `raw_hash`, comme `processed` : un payload inchangé garde le marqueur, y compris son effacement par `fetch_truncated` ; un payload modifié le recalcule.
        authors_truncated = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.authors_truncated
            ELSE staging.authors_truncated
        END,
        -- `entry_mode` garde la provenance de la création.
        -- Un document rendu par sa source efface le marqueur de disparition.
        disappeared_at = NULL,
        last_seen_at = now()
    RETURNING (xmax = 0) AS inserted,
              ((SELECT old_hash FROM old) IS DISTINCT FROM :raw_hash) AS changed
    """
).bindparams(bindparam("raw_data", type_=Jsonb))


class UpsertOutcome(StrEnum):
    """Issue de l'écriture d'une ligne de `staging`.

    - `NEW` : ligne insérée ;
    - `UPDATED` : ligne existante au contenu changé, réécrite ;
    - `UNCHANGED` : ligne revue au contenu identique, dont seule la date de dernière lecture change.
    """

    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"

    @classmethod
    def of(cls, *, inserted: bool, changed: bool) -> UpsertOutcome:
        """Classe le résultat de `StagingStore.upsert`. Une insertion prime : son changement de contenu est sans objet."""
        if inserted:
            return cls.NEW
        return cls.UPDATED if changed else cls.UNCHANGED


@dataclass(frozen=True)
class StagingRow:
    """Ligne de `staging` à normaliser."""

    id: int
    source_id: str
    doi: str | None
    raw_data: Mapping[str, JsonValue]


_COLUMNS = "id, source_id, doi, raw_data"


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


# Réécrit `raw_data` sans recalculer `raw_hash` : la ligne garde l'empreinte du document tronqué, que le moissonnage suivant retrouve. Lève le marqueur et repasse `processed = FALSE` : la normalisation réécrit les contributions sources complètes.
_COMPLETE_AUTHORS_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, processed = FALSE, authors_truncated = FALSE, last_seen_at = now()
    WHERE source = :source AND source_id = :source_id
    """
).bindparams(bindparam("raw_data", type_=Jsonb))

_CLEAR_TRUNCATED_SQL = text(
    "UPDATE staging SET authors_truncated = FALSE WHERE source = :source AND source_id = :source_id"
)


class StagingStore:
    """Écritures des documents rendus par les sources, lectures et marquages de `staging` par la normalisation.

    Le raw store reçoit chaque payload juste avant que `mark_done` le vide de la base. Par défaut, c'est celui de `get_raw_store()`, lu au premier `mark_done`.
    """

    def __init__(self, conn: Connection, raw_store: RawStore | None = None) -> None:
        self._conn = conn
        self._raw_store = raw_store

    def stage(
        self,
        source: str,
        record: Mapping[str, JsonValue],
        *,
        entry_mode: StagingEntryMode = StagingEntryMode.BULK,
        listed: bool = True,
    ) -> UpsertOutcome | None:
        """Écrit un document de `source`, identifié par l'adaptateur de la source, et efface les recherches infructueuses que le document dément.

        Les DOI d'un document démentent l'échec de leur recherche dans sa source, et, pour une agence d'enregistrement, auprès de doi.org. Un dépôt HAL dément l'échec de la recherche de son identifiant. `listed` : le document vient d'une réponse de liste, où la source peut plafonner les auteurs. Renvoie `None`, sans rien écrire, pour un document sans identifiant.
        """
        adapter = ADAPTERS[Source(source)]
        identity = adapter.identify(record)
        if identity is None:
            return None
        truncated = (
            listed and adapter.authors_truncated is not None and adapter.authors_truncated(record)
        )
        inserted, changed = self.upsert(
            source=source,
            source_id=identity.source_id,
            doi=identity.doi,
            raw_data=record,
            authors_truncated=truncated,
            entry_mode=entry_mode,
        )
        forget_failed_doi_lookups(self._conn, source, identity.dois)
        if PROFILES[Source(source)].registration_agency is not None:
            forget_failed_doi_lookups(self._conn, DOI_ORG, identity.dois)
        if source == Source.HAL:
            forget_failed_hal_id_lookup(self._conn, identity.source_id)
        return UpsertOutcome.of(inserted=inserted, changed=changed)

    def complete_authors(
        self, source: str, record: Mapping[str, JsonValue]
    ) -> UpsertOutcome | None:
        """Réécrit un document marqué tronqué par sa version complète, sans recalculer son empreinte.

        Tant que le moissonnage renvoie le même document tronqué, son empreinte égale celle en base, et l'écriture laisse la version complète en place. Renvoie `UPDATED`, ou `None` pour un document sans identifiant.
        """
        identity = ADAPTERS[Source(source)].identify(record)
        if identity is None:
            return None
        self._conn.execute(
            _COMPLETE_AUTHORS_SQL,
            {"raw_data": record, "source": source, "source_id": identity.source_id},
        )
        return UpsertOutcome.UPDATED

    def clear_truncated(self, source: str, source_id: str) -> None:
        """Lève le marqueur de troncature d'un document, sans toucher son contenu."""
        self._conn.execute(_CLEAR_TRUNCATED_SQL, {"source": source, "source_id": source_id})

    def upsert(
        self,
        *,
        source: str,
        source_id: str,
        doi: str | None,
        raw_data: Mapping[str, JsonValue],
        authors_truncated: bool = False,
        entry_mode: StagingEntryMode = StagingEntryMode.BULK,
    ) -> tuple[bool, bool]:
        """Écrit une ligne de `staging`, pour `stage` et pour les imports qui identifient eux-mêmes leurs lignes. L'appelant commite.

        Le contenu se réécrit, et la ligne repasse à normaliser, seulement si l'empreinte change (`change_detection_hash`). Une empreinte nulle en base force la réécriture. La date de dernière lecture change toujours. Un DOI manquant se renseigne, un DOI présent reste.

        Le marqueur de troncature des auteurs suit la même règle : il se pose seulement quand l'empreinte change, et garde sinon son effacement par `fetch_truncated`. La provenance (`entry_mode`) se pose à la création seulement.

        Renvoie `(inserted, changed)` : ligne insérée, contenu réécrit.
        """
        row = self._conn.execute(
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

    def count_pending_staging(self, source: str) -> int:
        row = self._conn.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM staging WHERE source = :source AND processed = FALSE"
            ),
            {"source": source},
        ).one_or_none()
        return row.cnt if row else 0

    def fetch_pending_staging(self, source: str, *, limit: int) -> list[StagingRow]:
        rows = self._conn.execute(
            text(f"""
                SELECT {_COLUMNS}
                FROM staging
                WHERE source = :source AND processed = FALSE
                ORDER BY id
                LIMIT :lim
            """),
            {"source": source, "lim": limit},
        )
        return rows_as(StagingRow, rows)

    def fetch_pending_staging_ids(self, source: str) -> list[int]:
        rows = self._conn.execute(
            text("""
                SELECT id FROM staging
                WHERE source = :source AND processed = FALSE
                ORDER BY id
            """),
            {"source": source},
        ).all()
        return [r.id for r in rows]

    def fetch_staging_by_ids(self, staging_ids: list[int]) -> list[StagingRow]:
        rows = self._conn.execute(
            text(f"""
                SELECT {_COLUMNS}
                FROM staging WHERE id = ANY(:ids)
                ORDER BY id
            """),
            {"ids": staging_ids},
        )
        return rows_as(StagingRow, rows)

    def discard_source_record(self, staging_id: int) -> None:
        delete_source_record_of_staging(self._conn, staging_id)

    def mark_done(self, staging_id: int) -> None:
        # `old` capture le payload avant de le vider. L'archivage au raw store se fait au mieux : un échec laisse la normalisation continuer, et la base reste la référence.
        row = self._conn.execute(_MARK_DONE_SQL, {"sid": staging_id}).one_or_none()
        if row is None or not row.raw_data:  # payload vide : rien à archiver
            return
        if self._raw_store is None:
            self._raw_store = get_raw_store()
        try:
            self._raw_store.put(row.source, row.source_id, stable_json_bytes(row.raw_data))
        except Exception:
            _logger.warning(
                "raw_store.put a échoué pour %s/%s (payload non archivé)",
                row.source,
                row.source_id,
                exc_info=True,
            )
