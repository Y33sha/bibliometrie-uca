"""Recherche dans theses.fr de la phase `fetch_missing` : tâche `fetch_missing.theses_by_nnt`.

NNT de thèses soutenues que d'autres sources contiennent (scanR, OpenAlex, HAL) et que le staging theses.fr n'a pas : thèses soutenues dans un autre établissement, liées au périmètre par un auteur, un directeur ou un membre du jury. Une requête à la fois, par la boucle commune (`pipeline.ingestion.common.lookup`).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, text

from domain.source_records.external_ids import ExternalIdType
from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.common.failed_lookups import pending_failed_lookup_sql, record_failed_lookup
from pipeline.ingestion.common.lookup import LookupChannel, look_up, one_at_a_time
from pipeline.ingestion.theses.api import fetch_thesis
from pipeline.runtime.observability.metrics import PhaseMetrics

_NNT = f"sr.external_ids ->> '{ExternalIdType.NNT}'"

_NNT_PENDING = pending_failed_lookup_sql(source_sql="'theses'", id_type="nnt", value_sql=_NNT)

_MISSING_NNTS_SQL = text(
    f"""
    SELECT DISTINCT {_NNT} AS nnt
    FROM source_records sr
    WHERE sr.source <> 'theses'
      AND {_NNT} IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM staging s WHERE s.source = 'theses' AND s.source_id = {_NNT}
      )
      AND NOT {_NNT_PENDING}
    ORDER BY 1
    """
)


def get_missing_nnts(conn: Connection, *, retry_after_days: int) -> list[str]:
    """NNT que des documents d'autres sources contiennent, absents du staging theses.fr. Écarte ceux déjà cherchés en vain : theses.fr attribue les NNT, l'échec est définitif."""
    return list(conn.execute(_MISSING_NNTS_SQL, {"retry_after_days": retry_after_days}).scalars())


async def fetch_missing_theses_by_nnt(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans theses.fr les thèses repérées par NNT dans d'autres sources et les écrit dans `staging`.

    Un NNT introuvable est inscrit dans `failed_lookups` et cherché de nouveau après `retry_after_days` jours. theses.fr indisponible laisse le NNT dans la sélection du run suivant.

    Compteurs de `look_up`, et `extras["not_found"]` = NNT introuvables.
    """
    nnts = get_missing_nnts(conn, retry_after_days=retry_after_days)
    return await look_up(
        conn,
        log,
        LookupChannel(
            source="theses",
            fetch=one_at_a_time(fetch_thesis),
            on_absent=lambda conn, nnt: record_failed_lookup(conn, "theses", "nnt", nnt),
            stage=lambda staging, thesis: staging.stage(
                "theses", thesis, entry_mode=StagingEntryMode.FETCH_MISSING_THESES
            ),
        ),
        nnts,
    )
