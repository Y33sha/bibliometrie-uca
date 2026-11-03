"""Copies des publications, lues sur les localisations de leurs enregistrements sources et sur l'URL de résolution de leur DOI."""

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import Connection, text

from domain.platforms.platform import PlatformType
from domain.publications.access import Copy, registered_url_copy
from domain.publications.licenses import License
from infrastructure.sql_fragments import under_active_embargo


def publication_copies(conn: Connection, publication_ids: Sequence[int]) -> dict[int, list[Copy]]:
    """Renvoie les copies des localisations des enregistrements sources de chaque publication (`Copy.of_location`), et la copie de l'URL de résolution de son DOI (`registered_url_copy`). Une publication sans copie est absente de la réponse. Pour un enregistrement source sous embargo, seule la copie à PDF, son fichier déposé, est sous embargo."""
    rows = conn.execute(
        text(f"""
            SELECT sr.publication_id, sr.source::text AS source, sr.doc_type::text AS doc_type,
                   l.url, l.version,
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
        copies[r.publication_id].append(
            Copy.of_location(
                r.url,
                version=r.version,
                declared_oa=r.declared_oa,
                arrival=r.arrival,
                embargoed=r.embargoed,
                license=License(r.license) if r.license else None,
                source_platform=r.platform,
                source_platform_type=PlatformType(r.platform_type) if r.platform_type else None,
                platform_openalex_id=r.platform_openalex_id,
                record_source=r.source,
                record_doc_type=r.doc_type,
            )
        )
    registered = conn.execute(
        text("""
            SELECT p.id, d.registered_url
            FROM publications p JOIN dois d ON d.doi = lower(p.doi)
            WHERE p.id = ANY(:ids) AND d.registered_url IS NOT NULL
        """),
        {"ids": list(publication_ids)},
    )
    for r in registered:
        if copy := registered_url_copy(r.registered_url):
            copies[r.id].append(copy)
    return dict(copies)
