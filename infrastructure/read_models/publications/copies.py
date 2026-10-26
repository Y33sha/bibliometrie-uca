"""Copies des publications, lues sur les localisations de leurs enregistrements sources."""

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import Connection, text

from domain.platforms.registry import HAL
from domain.publications.access import Copy
from domain.source_records.metadata_correction.shared_doi import CONVERGENCE_CASES
from infrastructure.sql_fragments import corrected_by


def publication_copies(conn: Connection, publication_ids: Sequence[int]) -> dict[int, list[Copy]]:
    """Localisations des enregistrements sources de chaque publication, hors formes secondaires. Une publication sans localisation manque de la réponse. La copie qu'un enregistrement HAL donne de HAL est décrite par sa plateforme."""
    rows = conn.execute(
        text(f"""
            SELECT sr.publication_id, l.url, l.version, l.is_oa,
                   pl.name AS platform, pl.openalex_id AS platform_openalex_id,
                   (sr.source = 'hal' AND pl.openalex_id = ANY(:hal_ids)) AS described_by_platform,
                   sr.id AS arrival
            FROM source_record_locations l
            JOIN source_records sr ON sr.id = l.source_record_id
            LEFT JOIN platforms pl ON pl.id = l.platform_id
            WHERE sr.publication_id = ANY(:ids)
              AND NOT COALESCE({corrected_by("doi", "sr")} = ANY(:convergence_cases), false)
        """),
        {
            "ids": list(publication_ids),
            "hal_ids": list(HAL.openalex_ids),
            "convergence_cases": list(CONVERGENCE_CASES),
        },
    ).all()
    copies: dict[int, list[Copy]] = defaultdict(list)
    for r in rows:
        copies[r.publication_id].append(
            Copy(
                url=r.url,
                version=r.version,
                is_oa=r.is_oa,
                platform=r.platform,
                platform_openalex_id=r.platform_openalex_id,
                described_by_platform=r.described_by_platform,
                arrival=r.arrival,
            )
        )
    return dict(copies)
