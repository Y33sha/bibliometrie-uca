"""Copies des publications, lues sur les localisations de leurs enregistrements sources."""

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import Connection, text

from domain.platforms.registry import HAL, known_platform_of_copy
from domain.publications.access import Copy
from domain.sources.registry import Source


def publication_copies(conn: Connection, publication_ids: Sequence[int]) -> dict[int, list[Copy]]:
    """Renvoie les localisations des enregistrements sources de chaque publication. Une publication sans localisation est absente de la réponse. La copie HAL d'un enregistrement HAL est décrite par sa plateforme."""
    rows = conn.execute(
        text("""
            SELECT sr.publication_id, sr.source::text AS source, l.url, l.version, l.is_oa,
                   pl.name AS platform, pl.openalex_id AS platform_openalex_id,
                   sr.id AS arrival
            FROM source_record_locations l
            JOIN source_records sr ON sr.id = l.source_record_id
            LEFT JOIN platforms pl ON pl.id = l.platform_id
            WHERE sr.publication_id = ANY(:ids)
        """),
        {"ids": list(publication_ids)},
    ).all()
    copies: dict[int, list[Copy]] = defaultdict(list)
    for r in rows:
        known = known_platform_of_copy(r.url, r.platform_openalex_id)
        copies[r.publication_id].append(
            Copy(
                url=r.url,
                version=r.version,
                is_oa=r.is_oa,
                platform=known.name if known else r.platform,
                known_platform=known,
                described_by_platform=r.source == Source.HAL and known is HAL,
                arrival=r.arrival,
            )
        )
    return dict(copies)
