"""Recalcul de l'état consolidé d'une publication depuis ses `source_records`."""

from collections.abc import Sequence
from enum import StrEnum
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.publications.access import access
from domain.publications.aggregation import (
    assign_publisher,
    refresh_from_sources as _refresh_aggregate,
)
from domain.publications.open_access import publication_oa_status
from domain.publications.publication import Publication
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from domain.source_records.corrections import stash_entry
from domain.source_records.identifiers import SourceIdentifier
from domain.source_records.keys import doi_keys
from domain.source_records.metadata_correction.rules import (
    MetadataForCorrection,
    effective_metadata,
)
from domain.source_records.source_record import SourceRecord
from domain.sources.registry import SOURCE_PRIORITY
from domain.types import JsonValue
from infrastructure.db.doi_targets import fetch_doi_targets
from infrastructure.db.rows import rows_as
from infrastructure.db.source_record_identifiers import identifiers_json_sql, parse_identifiers
from infrastructure.read_models.publications.copies import publication_copies
from pipeline.transformation.publications.store import PublicationStore


class _SourceRecordRow(NamedTuple):
    """Colonnes de `source_records` lues par l'agrégation."""

    id: int
    source: str
    source_id: str
    title: str
    publication_year: int | None
    doc_type: str | None
    identifiers: list[dict[str, str | None]]
    serial_id: int | None
    monograph_id: int | None
    container_title: str | None
    language: str | None
    oa_status: str | None
    is_retracted: bool | None
    abstract: str | None
    countries: list[str] | None
    urls: list[str] | None
    keywords: list[str] | None
    topics: dict[str, JsonValue] | None
    biblio: dict[str, JsonValue] | None
    source_extras: dict[str, JsonValue] | None
    license: str | None
    publisher_id: int | None


def _source_record_from_row(
    row: _SourceRecordRow, identifiers: tuple[SourceIdentifier, ...], doi_targets: dict[str, str]
) -> SourceRecord:
    """Construit le `SourceRecord` d'une ligne de `source_records`, tableaux convertis en tuples.

    Args:
        doi_targets: cible du DOI de chaque forme secondaire.
    """
    return SourceRecord(
        id=row.id,
        source=row.source,
        source_id=row.source_id,
        title=row.title,
        publication_year=row.publication_year,
        doc_type=row.doc_type,
        dois=doi_keys(identifiers, doi_targets),
        serial_id=row.serial_id,
        monograph_id=row.monograph_id,
        container_title=row.container_title,
        language=row.language,
        oa_status=row.oa_status,
        is_retracted=row.is_retracted,
        abstract=row.abstract,
        countries=tuple(row.countries or ()),
        urls=tuple(row.urls or ()),
        keywords=tuple(row.keywords or ()),
        topics=row.topics,
        biblio=row.biblio,
        source_extras=row.source_extras,
        license=row.license,
        publisher_id=row.publisher_id,
    )


def source_records_of(conn: Connection, publication_id: int) -> list[SourceRecord]:
    """Renvoie les enregistrements sources d'une publication, pour l'agrégation. Le DOI d'une forme secondaire est remplacé par sa cible (`doi_targets`)."""
    result = conn.execute(
        text(f"""
            SELECT sr.id, sr.source::text AS source, sr.source_id,
                   sr.title, sr.publication_year, sr.doc_type::text AS doc_type,
                   {identifiers_json_sql("sr.id")} AS identifiers,
                   sr.serial_id, sr.monograph_id, sr.container_title, sr.language,
                   sr.oa_status::text AS oa_status, sr.is_retracted, sr.abstract,
                   sr.countries, sr.urls, sr.keywords,
                   sr.topics, sr.biblio, sr.source_extras, sr.license::text AS license,
                   sr.publisher_id
            FROM source_records sr
            WHERE sr.publication_id = :id
        """),
        {"id": publication_id},
    )
    rows = [(row, parse_identifiers(row.identifiers)) for row in rows_as(_SourceRecordRow, result)]
    doi_targets = fetch_doi_targets(conn, (i for _, ids in rows for i in ids))
    return [_source_record_from_row(row, ids, doi_targets) for row, ids in rows]


def monograph_serial_ids(conn: Connection, monograph_ids: Sequence[int]) -> dict[int, int | None]:
    """Renvoie la collection (`serial_id`) de chaque monographie, pour l'agrégation."""
    rows = conn.execute(
        text("SELECT id, serial_id FROM monographs WHERE id = ANY(:ids)"),
        {"ids": list(monograph_ids)},
    )
    return {r.id: r.serial_id for r in rows}


def unpaywall_verdict(conn: Connection, doi: str) -> str | None:
    """Renvoie le verdict d'Unpaywall sur un DOI, `None` sans verdict."""
    return conn.execute(
        text("SELECT oa_status::text FROM unpaywall WHERE doi = :doi"), {"doi": doi}
    ).scalar_one_or_none()


def crossref_prefix_publishers(conn: Connection, prefixes: Sequence[str]) -> dict[str, int]:
    """Renvoie le titulaire de chaque préfixe DOI Crossref connu, pour l'éditeur des publications."""
    rows = conn.execute(
        text(
            "SELECT prefix, publisher_id FROM doi_prefixes"
            " WHERE prefix = ANY(:prefixes) AND ra = 'Crossref' AND publisher_id IS NOT NULL"
        ),
        {"prefixes": list(prefixes)},
    )
    return {r.prefix: r.publisher_id for r in rows}


def serial_oa_model_of(conn: Connection, serial_id: int) -> str | None:
    """Renvoie le modèle open access d'une revue, ou `None`, pour le statut open access de ses publications."""
    return conn.execute(
        text("SELECT oa_model::text FROM serials WHERE id = :id"),
        {"id": serial_id},
    ).scalar_one_or_none()


def serial_type_of(conn: Connection, serial_id: int) -> str | None:
    """Renvoie le type d'une revue, ou `None`, pour le rejeu des corrections dépendantes de ce type."""
    return conn.execute(
        text("SELECT serial_type::text FROM serials WHERE id = :id"),
        {"id": serial_id},
    ).scalar_one_or_none()


def _refresh_sources(conn: Connection, publication_id: int) -> None:
    """Recalcule `publications.sources` depuis les enregistrements sources de la publication."""
    conn.execute(
        text("""
            UPDATE publications SET sources = COALESCE(sub.srcs, '{}'),
                                    updated_at = now()
            FROM (
                SELECT array_agg(
                    DISTINCT CAST(source AS source_type)
                    ORDER BY CAST(source AS source_type)
                ) AS srcs
                FROM source_records
                WHERE publication_id = :id
            ) sub
            WHERE id = :id
        """),
        {"id": publication_id},
    )


class RefreshVerdict(StrEnum):
    """Issue du recalcul d'une publication depuis ses `source_records`."""

    SAVED = "saved"
    ABSENT = "absent"
    NO_SOURCE = "no_source"
    INADMISSIBLE_TYPE = "inadmissible_type"


def refresh_from_sources(conn: Connection, publication_id: int) -> RefreshVerdict:
    """Recalcule les métadonnées d'une publication depuis ses enregistrements sources.

    Recalcul complet : lit tous les enregistrements sources rattachés, agrège (`domain.publications.aggregation`), rejoue les corrections nées de l'arbitrage, choisit l'URL du texte intégral (`domain.publications.access`), déduit le statut open access des copies (`domain.publications.open_access`), pose l'éditeur d'après le type corrigé, persiste. Rattrape les métadonnées périmées (`ongoing_thesis` → `thesis` après soutenance).

    Une publication sans enregistrement source (`NO_SOURCE`), ou de `doc_type` résolu dans `OUT_OF_SCOPE_DOC_TYPES` (`INADMISSIBLE_TYPE`), reste en l'état. Le module du cycle de vie la supprime sur ce verdict.

    Modifie seulement la publication reçue, hors `notes`. La réconciliation décide quels enregistrements sources forment une même œuvre.
    """
    store = PublicationStore(conn)
    publication = store.find_by_id(publication_id)
    if publication is None:
        return RefreshVerdict.ABSENT

    sources = source_records_of(conn, publication_id)
    if not sources:
        return RefreshVerdict.NO_SOURCE

    # L'agrégation part des colonnes corrigées par la phase `metadata_correction`.
    monograph_ids = sorted({s.monograph_id for s in sources if s.monograph_id is not None})
    _refresh_aggregate(
        publication,
        sources,
        source_priority=SOURCE_PRIORITY,
        monograph_serials=monograph_serial_ids(conn, monograph_ids) if monograph_ids else {},
    )
    _apply_canonical_doc_type_correction(
        publication,
        serial_type=serial_type_of(conn, publication.serial_id)
        if publication.serial_id is not None
        else None,
    )
    copies = publication_copies(conn, [publication_id]).get(publication_id, [])
    publication.best_copy_url = access(
        copies, doi=str(publication.doi) if publication.doi else None
    ).url
    publication.oa_status = publication_oa_status(
        copies,
        sources,
        unpaywall=unpaywall_verdict(conn, publication.doi.value) if publication.doi else None,
        has_serial=publication.serial_id is not None,
        serial_oa_model=serial_oa_model_of(conn, publication.serial_id)
        if publication.serial_id is not None
        else None,
    )
    prefixes = [publication.doi.prefix.value] if publication.doi else []
    assign_publisher(
        publication,
        sources,
        source_priority=SOURCE_PRIORITY,
        prefix_publishers=crossref_prefix_publishers(conn, prefixes) if prefixes else {},
    )

    if publication.doc_type in OUT_OF_SCOPE_DOC_TYPES:
        return RefreshVerdict.INADMISSIBLE_TYPE

    store.save(publication)
    _refresh_sources(conn, publication_id)
    return RefreshVerdict.SAVED


def _apply_canonical_doc_type_correction(
    publication: Publication, *, serial_type: str | None
) -> None:
    """Rejoue les corrections de `doc_type` sur la publication, après l'arbitrage.

    L'arbitrage prend chaque champ de la source la plus prioritaire qui le renseigne. La publication peut donc réunir un `doc_type` d'une source et un `serial_id` d'une autre, combinaison absente des corrections par source.

    Modifie `publication.doc_type` et réécrit `publication.corrections` : type arbitré et règle, ou vide sans correction. Idempotent.

    Args:
        serial_type: type de la revue `publication.serial_id`.
    """
    corrected = effective_metadata(
        MetadataForCorrection.for_publication(
            title=publication.title,
            doc_type=publication.doc_type,
            doi=str(publication.doi) if publication.doi else None,
            serial_id=publication.serial_id,
            serial_type=serial_type,
        )
    ).doc_type
    publication.corrections = {}
    if corrected is not None and corrected.value != publication.doc_type:
        publication.corrections = {
            "doc_type": stash_entry(publication.doc_type, corrected.rule.value)
        }
        publication.doc_type = corrected.value
