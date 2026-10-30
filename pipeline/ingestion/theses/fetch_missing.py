"""Recherche dans theses.fr de la phase `fetch_missing` : tâche `fetch_missing.theses_by_nnt`.

Les NNT cherchés sont ceux de thèses soutenues présentes dans d'autres sources (ScanR, OpenAlex, HAL) et absentes du staging theses.fr : thèses soutenues dans un autre établissement, liées au périmètre par un auteur, un directeur ou un membre du jury. Une requête à la fois, par la boucle commune (`pipeline.ingestion.common.lookup`).
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, text

from domain.source_records.identifiers import SourceIdentifierType
from domain.sources.staging import StagingEntryMode
from infrastructure.db.source_record_identifiers import first_of_its_type_sql
from pipeline.ingestion.common.failed_lookups import pending_failed_lookup_sql, record_failed_lookup
from pipeline.ingestion.common.lookup import LookupChannel, look_up, one_at_a_time
from pipeline.ingestion.theses.api import fetch_thesis
from pipeline.runtime.observability.metrics import PhaseMetrics

_NNT_PENDING = pending_failed_lookup_sql(
    source_sql="'theses'", id_type="nnt", value_sql="n.id_value"
)

# Le NNT d'un enregistrement source est son NNT actif de rôle le plus fort, puis de plus petite valeur.
_MISSING_NNTS_SQL = text(
    f"""
    SELECT DISTINCT n.id_value AS nnt
    FROM source_records sr
    JOIN source_record_identifiers n
      ON n.source_record_id = sr.id AND n.id_type = '{SourceIdentifierType.NNT}'
         AND {first_of_its_type_sql("n")}
    WHERE sr.source <> 'theses'
      AND NOT EXISTS (
          SELECT 1 FROM staging s WHERE s.source = 'theses' AND s.source_id = n.id_value
      )
      AND NOT {_NNT_PENDING}
    ORDER BY 1
    """
)


def get_missing_nnts(conn: Connection, *, retry_after_days: int) -> list[str]:
    """Renvoie les NNT présents dans des enregistrements sources d'autres sources et absents du staging theses.fr.

    Les NNT déjà cherchés en vain sont écartés : theses.fr attribue les NNT, l'échec est définitif.
    """
    return list(conn.execute(_MISSING_NNTS_SQL, {"retry_after_days": retry_after_days}).scalars())


async def fetch_missing_theses_by_nnt(
    conn: Connection, log: logging.Logger, *, retry_after_days: int
) -> PhaseMetrics:
    """Cherche dans theses.fr les thèses repérées par NNT dans d'autres sources et les écrit dans `staging`.

    Un NNT introuvable est inscrit dans `failed_lookups`. Quand theses.fr est indisponible, le NNT reste dans la sélection du run suivant.

    Renvoie les compteurs de `look_up`, avec le nombre de NNT introuvables (`not_found`).
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
                "theses", thesis, entry_mode=StagingEntryMode.FETCH_MISSING_NNT
            ),
        ),
        nnts,
    )
