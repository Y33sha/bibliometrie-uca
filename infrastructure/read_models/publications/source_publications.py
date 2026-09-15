"""Enregistrements sources d'une publication, confrontés dans le volet de l'administration."""

from collections.abc import Mapping

from sqlalchemy import Connection, Row, text

from application.ports.read_models.publications_queries import (
    PublicationSourcesResponse,
    SourcePublicationMetadataOut,
)
from domain.source_publications.external_ids import ExternalIdType

# L'ISSN identifie la revue : il figure avec elle, depuis `biblio`.
_JOURNAL_IDENTIFIERS = frozenset({ExternalIdType.ISSN})


def _identifiers(external_ids: Mapping[str, object]) -> dict[str, list[str]]:
    """Valeurs textuelles de `external_ids` hors ISSN, en listes : une valeur isolée devient une liste d'un élément."""
    out: dict[str, list[str]] = {}
    for key, value in external_ids.items():
        if key in _JOURNAL_IDENTIFIERS:
            continue
        values = value if isinstance(value, list) else [value]
        strings = [v for v in values if isinstance(v, str) and v]
        if strings:
            out[key] = strings
    return out


def _text(mapping: Mapping[str, object], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) and value else None


def _pages(biblio: Mapping[str, object]) -> str | None:
    """Plage de pages telle que la source la donne (`pages` pour HAL, `page` pour Crossref), sinon composée de `first_page` et `last_page`."""
    if given := _text(biblio, "pages") or _text(biblio, "page"):
        return given
    first, last = _text(biblio, "first_page"), _text(biblio, "last_page")
    if first and last and first != last:
        return f"{first}-{last}"
    return first or last


def _record(r: Row[tuple[object, ...]]) -> SourcePublicationMetadataOut:
    biblio: Mapping[str, object] = r.biblio or {}
    journal = biblio.get("journal")
    raw_journal: Mapping[str, object] = journal if isinstance(journal, Mapping) else {}
    return SourcePublicationMetadataOut(
        id=r.id,
        source=r.source,
        source_id=r.source_id,
        doi=r.doi,
        identifiers=_identifiers(r.external_ids),
        title=r.title,
        title_normalized=r.title_normalized,
        doc_type=r.doc_type,
        pub_year=r.pub_year,
        language=r.language,
        language_name=r.language_name,
        language_raw=r.language_raw,
        oa_status=r.oa_status,
        journal_id=r.journal_id,
        journal_title=r.journal_title,
        journal_raw_title=_text(raw_journal, "title"),
        journal_raw_issn=_text(raw_journal, "issn"),
        journal_raw_eissn=_text(raw_journal, "eissn"),
        publisher_id=r.publisher_id,
        publisher_name=r.publisher_name,
        publisher_raw_name=_text(biblio, "publisher"),
        container_title=r.container_title,
        volume=_text(biblio, "volume"),
        issue=_text(biblio, "issue"),
        pages=_pages(biblio),
        article_number=_text(biblio, "article_number"),
    )


def get_publication_sources(conn: Connection, pub_id: int) -> PublicationSourcesResponse | None:
    """Métadonnées de chaque enregistrement source de la publication `pub_id`, ou `None` si la publication n'existe pas."""
    title = conn.execute(
        text("SELECT title FROM publications WHERE id = :pid"), {"pid": pub_id}
    ).scalar_one_or_none()
    if title is None:
        return None
    rows = conn.execute(
        text("""
            SELECT sp.id, sp.source::text AS source, sp.source_id, sp.doi, sp.external_ids,
                   sp.title, sp.title_normalized, sp.doc_type, sp.pub_year, sp.language,
                   lang.name AS language_name,
                   sp.raw_metadata->'language'->>'raw' AS language_raw,
                   sp.oa_status, sp.container_title, sp.biblio,
                   j.id AS journal_id, j.title AS journal_title,
                   pub.id AS publisher_id, pub.name AS publisher_name
            FROM source_publications sp
            LEFT JOIN journals j ON j.id = sp.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            LEFT JOIN languages lang ON lang.code = sp.language
            WHERE sp.publication_id = :pid
            ORDER BY sp.source, sp.source_id
        """),
        {"pid": pub_id},
    ).all()
    return PublicationSourcesResponse(title=title, source_publications=[_record(r) for r in rows])
