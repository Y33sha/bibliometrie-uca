"""Enregistrements sources d'une publication et leurs contributions sources, confrontés dans le volet de l'administration."""

from collections.abc import Mapping

from sqlalchemy import Connection, Row, text

from domain.source_records.biblio import BiblioKey, JournalKey
from domain.source_records.corrections import CORRECTED_BY, RAW, CorrectionKey
from infrastructure.db.source_record_identifiers import source_record_doi_sql
from infrastructure.read_models.publications.detail import structures_by_id
from infrastructure.read_models.publications.models import (
    ExternalIdentifierOut,
    PublicationSourcesResponse,
    SourceContributionOut,
    SourceRecordMetadataOut,
)
from infrastructure.read_models.sql_fragments import (
    contributor_display_name,
    source_contribution_structure_ids,
)


def _text(mapping: Mapping[str, object], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) and value else None


def _pages(biblio: Mapping[str, object]) -> str | None:
    """Plage de pages composée de `first_page` et `last_page`."""
    first, last = _text(biblio, BiblioKey.FIRST_PAGE), _text(biblio, BiblioKey.LAST_PAGE)
    if first and last and first != last:
        return f"{first}-{last}"
    return first or last


def _record(r: Row[tuple[object, ...]]) -> SourceRecordMetadataOut:
    biblio: Mapping[str, object] = r.biblio or {}
    journal = biblio.get(BiblioKey.JOURNAL)
    raw_journal: Mapping[str, object] = journal if isinstance(journal, Mapping) else {}
    return SourceRecordMetadataOut(
        id=r.id,
        source=r.source,
        source_id=r.source_id,
        doi=r.doi,
        identifiers=[ExternalIdentifierOut(**i) for i in r.identifiers],
        title=r.title,
        title_normalized=r.title_normalized,
        doc_type=r.doc_type,
        raw_doc_type=r.raw_doc_type,
        doc_type_uncorrected=r.doc_type_uncorrected,
        doc_type_corrected_by=r.doc_type_corrected_by,
        publication_year=r.publication_year,
        language=r.language,
        language_name=r.language_name,
        language_raw=r.language_raw,
        oa_status=r.oa_status,
        serial_id=r.serial_id,
        journal_title=r.journal_title,
        journal_raw_title=_text(raw_journal, JournalKey.TITLE),
        journal_raw_issn=_text(raw_journal, JournalKey.ISSN),
        journal_raw_eissn=_text(raw_journal, JournalKey.EISSN),
        publisher_id=r.publisher_id,
        publisher_name=r.publisher_name,
        publisher_raw_name=_text(biblio, BiblioKey.PUBLISHER),
        container_title=r.container_title,
        volume=_text(biblio, BiblioKey.VOLUME),
        issue=_text(biblio, BiblioKey.ISSUE),
        pages=_pages(biblio),
        article_number=_text(biblio, BiblioKey.ARTICLE_NUMBER),
    )


def _source_contributions(conn: Connection, publication_id: int) -> list[SourceContributionOut]:
    """Contributions sources des enregistrements sources de la publication, hors doublons d'auteur et collectifs, exclus de l'alignement, avec leur contribution et leur entrée dans la contribution."""
    rows = conn.execute(
        text(f"""
            SELECT sc.id, sc.source_record_id, sc.author_position AS position,
                   {contributor_display_name()} AS full_name, sc.roles, g.person_id,
                   sc.in_perimeter, sc.countries,
                   (SELECT array_agg(structure_id ORDER BY structure_id)
                    FROM ({source_contribution_structure_ids("sc")}) ids) AS structure_ids,
                   (SELECT string_agg(addr.raw_text, ' | ' ORDER BY addr.id)
                    FROM source_contribution_addresses sca
                    JOIN addresses addr ON addr.id = sca.address_id
                    WHERE sca.source_contribution_id = sc.id) AS raw_affiliation,
                   gs.contribution_id, g.reference_position, gs.method::text AS method,
                   gs.score, gs.margin
            FROM source_records sr
            JOIN source_contributions sc ON sc.source_record_id = sr.id
            LEFT JOIN aligned_source_contributions gs ON gs.source_contribution_id = sc.id
            LEFT JOIN contributions g ON g.id = gs.contribution_id
            WHERE sr.publication_id = :pid AND sc.duplicate_of IS NULL AND NOT sc.collective
            ORDER BY sc.source_record_id, sc.author_position NULLS LAST, sc.id
        """),  # noqa: S608
        {"pid": publication_id},
    ).all()
    return [
        SourceContributionOut(
            id=r.id,
            source_record_id=r.source_record_id,
            position=r.position,
            full_name=r.full_name,
            roles=r.roles,
            person_id=r.person_id,
            in_perimeter=r.in_perimeter,
            structure_ids=r.structure_ids,
            raw_affiliation=r.raw_affiliation,
            countries=r.countries,
            contribution_id=r.contribution_id,
            reference_position=r.reference_position,
            method=r.method,
            score=r.score,
            margin=r.margin,
        )
        for r in rows
    ]


class PublicationSourceRecordQueries:
    _conn: Connection

    def get_publication_sources(self, publication_id: int) -> PublicationSourcesResponse | None:
        """Métadonnées et contributions sources de chaque enregistrement source de la publication `publication_id`, ou `None` si la publication n'existe pas."""
        title = self._conn.execute(
            text("SELECT title FROM publications WHERE id = :pid"), {"pid": publication_id}
        ).scalar_one_or_none()
        if title is None:
            return None
        rows = self._conn.execute(
            text(f"""
                SELECT sr.id, sr.source::text AS source, sr.source_id,
                       {source_record_doi_sql("sr")} AS doi,
                       COALESCE((
                           SELECT jsonb_agg(jsonb_build_object('type', i.id_type, 'value', i.id_value)
                                            ORDER BY i.id_type, i.id_value)
                           FROM source_record_identifiers i
                           WHERE i.source_record_id = sr.id AND i.removed_by IS NULL
                             AND (i.id_type <> 'doi'
                                  OR i.id_value IS DISTINCT FROM {source_record_doi_sql("sr")})
                       ), '[]'::jsonb) AS identifiers,
                       sr.title, sr.title_normalized, sr.doc_type, sr.raw_doc_type,
                       sr.corrections -> '{CorrectionKey.DOC_TYPE}' ->> '{RAW}' AS doc_type_uncorrected,
                       sr.corrections -> '{CorrectionKey.DOC_TYPE}' ->> '{CORRECTED_BY}'
                           AS doc_type_corrected_by,
                       sr.publication_year, sr.language,
                       lang.name AS language_name,
                       CASE WHEN sr.raw_language IS DISTINCT FROM sr.language
                            THEN sr.raw_language END AS language_raw,
                       sr.oa_status, sr.container_title, sr.biblio,
                       j.id AS serial_id, j.title AS journal_title,
                       pub.id AS publisher_id, pub.name AS publisher_name
                FROM source_records sr
                LEFT JOIN serials j ON j.id = sr.serial_id
                LEFT JOIN publishers pub ON pub.id = sr.publisher_id
                LEFT JOIN languages lang ON lang.code = sr.language
                WHERE sr.publication_id = :pid
                ORDER BY sr.source, sr.source_id
            """),  # noqa: S608 — fragments rendus depuis des alias de la requête
            {"pid": publication_id},
        ).all()
        source_contributions = _source_contributions(self._conn, publication_id)
        return PublicationSourcesResponse(
            title=title,
            source_records=[_record(r) for r in rows],
            source_contributions=source_contributions,
            structures=structures_by_id(
                self._conn, {sid for s in source_contributions for sid in s.structure_ids or []}
            ),
        )
