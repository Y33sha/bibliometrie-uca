"""Copies des publications, lues sur les localisations de leurs enregistrements sources."""

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import Connection, text

from domain.platforms.platform import PlatformType
from domain.platforms.registry import HAL, known_platform_of_copy, platform_type_of_copy
from domain.publications.access import Copy
from domain.publications.licenses import License
from domain.sources.registry import Source
from infrastructure.sql_fragments import under_active_embargo


def publication_copies(conn: Connection, publication_ids: Sequence[int]) -> dict[int, list[Copy]]:
    """Renvoie les localisations des enregistrements sources de chaque publication. Une publication sans localisation est absente de la réponse. Le fichier déposé d'un enregistrement source sous embargo, sa copie à PDF, est fermé jusqu'à la fin de l'embargo. La copie HAL d'un enregistrement HAL est décrite par sa plateforme."""
    rows = conn.execute(
        text(f"""
            SELECT sr.publication_id, sr.source::text AS source, l.url, l.version,
                   l.is_oa AS declared_oa,
                   l.pdf_url IS NOT NULL AND {under_active_embargo("sr")} AS embargoed,
                   l.license::text AS license, pl.name AS platform,
                   pl.openalex_id AS platform_openalex_id, pl.platform_type::text AS platform_type,
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
                is_oa=r.declared_oa and not r.embargoed,
                platform=known.name if known else r.platform,
                known_platform=known,
                platform_type=platform_type_of_copy(r.url, r.platform_openalex_id)
                or (PlatformType(r.platform_type) if r.platform_type else None),
                license=License(r.license) if r.license else None,
                embargoed=r.embargoed,
                described_by_platform=r.source == Source.HAL and known is HAL,
                arrival=r.arrival,
            )
        )
    return dict(copies)
