"""Enregistrements sources d'une publication et leurs signatures, confrontés dans le volet de l'administration."""

from collections.abc import Mapping

from sqlalchemy import Connection, Row, text

from application.ports.read_models.publications_queries import (
    PublicationSourcesResponse,
    SourceRecordMetadataOut,
    SourceSignatureOut,
)
from infrastructure.read_models.publications.detail import structures_by_id
from infrastructure.read_models.sql_fragments import signature_display_name
from infrastructure.sql_fragments import stashed_raw


def _identifiers(external_ids: Mapping[str, object]) -> dict[str, list[str]]:
    """Valeurs textuelles de `external_ids`, en listes : une valeur isolée devient une liste d'un élément."""
    out: dict[str, list[str]] = {}
    for key, value in external_ids.items():
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


def _record(r: Row[tuple[object, ...]]) -> SourceRecordMetadataOut:
    biblio: Mapping[str, object] = r.biblio or {}
    journal = biblio.get("journal")
    raw_journal: Mapping[str, object] = journal if isinstance(journal, Mapping) else {}
    return SourceRecordMetadataOut(
        id=r.id,
        source=r.source,
        source_id=r.source_id,
        doi=r.doi,
        identifiers=_identifiers(r.external_ids),
        title=r.title,
        title_normalized=r.title_normalized,
        doc_type=r.doc_type,
        publication_year=r.publication_year,
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


def _signatures(conn: Connection, pub_id: int) -> list[SourceSignatureOut]:
    """Signatures des enregistrements de la publication, avec leur groupe et leur entrée dans le groupe."""
    rows = conn.execute(
        text(f"""
            SELECT sa.id, sa.source_record_id, sa.author_position AS position,
                   {signature_display_name()} AS full_name, sa.roles, sa.person_id,
                   sa.in_perimeter, sa.collective, sa.countries,
                   (SELECT array_agg(sas.structure_id ORDER BY sas.structure_id)
                    FROM source_contribution_structures sas
                    WHERE sas.source_contribution_id = sa.id) AS structure_ids,
                   (SELECT string_agg(addr.raw_text, ' | ' ORDER BY addr.id)
                    FROM source_contribution_addresses saa
                    JOIN addresses addr ON addr.id = saa.address_id
                    WHERE saa.source_contribution_id = sa.id) AS raw_affiliation,
                   gs.group_id, g.reference_position AS group_position, gs.method::text AS method,
                   gs.score, gs.margin
            FROM source_records sp
            JOIN source_contributions sa ON sa.source_record_id = sp.id
            LEFT JOIN source_contribution_group_members gs ON gs.source_contribution_id = sa.id
            LEFT JOIN source_contribution_groups g ON g.id = gs.group_id
            WHERE sp.publication_id = :pid
            ORDER BY sa.source_record_id, sa.author_position NULLS LAST, sa.id
        """),  # noqa: S608
        {"pid": pub_id},
    ).all()
    return [
        SourceSignatureOut(
            id=r.id,
            source_record_id=r.source_record_id,
            position=r.position,
            full_name=r.full_name,
            roles=r.roles,
            person_id=r.person_id,
            in_perimeter=r.in_perimeter,
            collective=r.collective,
            structure_ids=r.structure_ids,
            raw_affiliation=r.raw_affiliation,
            countries=r.countries,
            group_id=r.group_id,
            group_position=r.group_position,
            method=r.method,
            score=r.score,
            margin=r.margin,
        )
        for r in rows
    ]


def get_publication_sources(conn: Connection, pub_id: int) -> PublicationSourcesResponse | None:
    """Métadonnées et signatures de chaque enregistrement source de la publication `pub_id`, ou `None` si la publication n'existe pas."""
    title = conn.execute(
        text("SELECT title FROM publications WHERE id = :pid"), {"pid": pub_id}
    ).scalar_one_or_none()
    if title is None:
        return None
    rows = conn.execute(
        text(f"""
            SELECT sp.id, sp.source::text AS source, sp.source_id, sp.doi, sp.external_ids,
                   sp.title, sp.title_normalized, sp.doc_type, sp.publication_year, sp.language,
                   lang.name AS language_name,
                   {stashed_raw("language")} AS language_raw,
                   sp.oa_status, sp.container_title, sp.biblio,
                   j.id AS journal_id, j.title AS journal_title,
                   pub.id AS publisher_id, pub.name AS publisher_name
            FROM source_records sp
            LEFT JOIN journals j ON j.id = sp.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            LEFT JOIN languages lang ON lang.code = sp.language
            WHERE sp.publication_id = :pid
            ORDER BY sp.source, sp.source_id
        """),
        {"pid": pub_id},
    ).all()
    signatures = _signatures(conn, pub_id)
    return PublicationSourcesResponse(
        title=title,
        source_records=[_record(r) for r in rows],
        signatures=signatures,
        structures=structures_by_id(
            conn, {sid for s in signatures for sid in s.structure_ids or []}
        ),
    )
