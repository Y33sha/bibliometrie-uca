"""Recalcul de l'état consolidé des publications depuis leurs `source_records`, par lot : chaque lecture porte sur tout le lot."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from enum import StrEnum
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.publications.access import access
from domain.publications.aggregation import (
    assign_publisher,
    refresh_from_sources as _refresh_aggregate,
)
from domain.publications.dates import PublicationDate
from domain.publications.open_access import is_restricted, publication_oa_status
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
from infrastructure.sql_fragments import under_active_embargo
from pipeline.transformation.publications.store import PublicationStore


class _SourceRecordRow(NamedTuple):
    """Colonnes de `source_records` lues par l'agrégation."""

    publication_id: int
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
    is_retracted: bool | None
    abstract: str | None
    countries: list[str] | None
    urls: list[str] | None
    keywords: list[str] | None
    biblio: dict[str, JsonValue] | None
    source_extras: dict[str, JsonValue] | None
    license: str | None
    publisher_id: int | None
    publication_date: date | None
    publication_date_precision: str | None
    impact: dict[str, JsonValue] | None


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
        dois=doi_keys(identifiers, doi_targets, row.doc_type),
        serial_id=row.serial_id,
        monograph_id=row.monograph_id,
        container_title=row.container_title,
        language=row.language,
        is_retracted=row.is_retracted,
        abstract=row.abstract,
        countries=tuple(row.countries or ()),
        urls=tuple(row.urls or ()),
        keywords=tuple(row.keywords or ()),
        biblio=row.biblio,
        source_extras=row.source_extras,
        license=row.license,
        publisher_id=row.publisher_id,
        publication_date=PublicationDate.stored(
            row.publication_date, row.publication_date_precision
        ),
        impact=row.impact,
    )


def source_records_of(
    conn: Connection, publication_ids: Sequence[int]
) -> dict[int, list[SourceRecord]]:
    """Renvoie les enregistrements sources de chaque publication, pour l'agrégation, dans l'ordre d'arrivée : il départage deux enregistrements sources d'une même source. Le DOI d'une forme secondaire est remplacé par sa cible (`doi_targets`). Une publication sans enregistrement source est absente de la réponse."""
    result = conn.execute(
        text(f"""
            SELECT sr.publication_id, sr.id, sr.source::text AS source, sr.source_id,
                   sr.title, sr.publication_year, sr.doc_type::text AS doc_type,
                   {identifiers_json_sql("sr.id")} AS identifiers,
                   sr.serial_id, sr.monograph_id, sr.container_title, sr.language,
                   sr.is_retracted, sr.abstract,
                   sr.countries, sr.urls, sr.keywords,
                   sr.biblio, sr.source_extras, sr.license::text AS license,
                   sr.publisher_id, sr.publication_date,
                   sr.publication_date_precision::text AS publication_date_precision,
                   sr.impact
            FROM source_records sr
            WHERE sr.publication_id = ANY(:ids)
            ORDER BY sr.publication_id, sr.id
        """),
        {"ids": list(publication_ids)},
    )
    rows = [(row, parse_identifiers(row.identifiers)) for row in rows_as(_SourceRecordRow, result)]
    doi_targets = fetch_doi_targets(conn, (i for _, ids in rows for i in ids))
    by_publication: dict[int, list[SourceRecord]] = {}
    for row, ids in rows:
        by_publication.setdefault(row.publication_id, []).append(
            _source_record_from_row(row, ids, doi_targets)
        )
    return by_publication


def monograph_serial_ids(conn: Connection, monograph_ids: Sequence[int]) -> dict[int, int | None]:
    """Renvoie la collection (`serial_id`) de chaque monographie, pour l'agrégation."""
    rows = conn.execute(
        text("SELECT id, serial_id FROM monographs WHERE id = ANY(:ids)"),
        {"ids": list(monograph_ids)},
    )
    return {r.id: r.serial_id for r in rows}


def unpaywall_verdicts(conn: Connection, dois: Sequence[str]) -> dict[str, str | None]:
    """Renvoie le verdict d'Unpaywall sur chaque DOI connu, `None` sans verdict."""
    rows = conn.execute(
        text("SELECT doi, unpaywall_oa_status::text AS verdict FROM dois WHERE doi = ANY(:dois)"),
        {"dois": list(dois)},
    )
    return {r.doi: r.verdict for r in rows}


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


def embargoed_publications(conn: Connection, publication_ids: Sequence[int]) -> set[int]:
    """Renvoie les publications dont un enregistrement source est sous embargo actif."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT sr.publication_id FROM source_records sr"
            f" WHERE sr.publication_id = ANY(:ids) AND {under_active_embargo('sr')}"
        ),
        {"ids": list(publication_ids)},
    )
    return set(rows.scalars())


class SerialFacts(NamedTuple):
    """Champs d'une revue lus par le recalcul de ses publications."""

    serial_type: str | None
    """Pour le rejeu des corrections dépendantes du type de la revue."""
    oa_model: str | None
    """Pour le statut open access."""


def serial_facts(conn: Connection, serial_ids: Sequence[int]) -> dict[int, SerialFacts]:
    """Renvoie le type et le modèle open access de chaque revue connue."""
    rows = conn.execute(
        text(
            "SELECT id, serial_type::text AS serial_type, oa_model::text AS oa_model"
            " FROM serials WHERE id = ANY(:ids)"
        ),
        {"ids": list(serial_ids)},
    )
    return {r.id: SerialFacts(r.serial_type, r.oa_model) for r in rows}


class RefreshVerdict(StrEnum):
    """Issue du recalcul d'une publication depuis ses `source_records`."""

    SAVED = "saved"
    ABSENT = "absent"
    NO_SOURCE = "no_source"
    INADMISSIBLE_TYPE = "inadmissible_type"


class Consolidation(NamedTuple):
    """Recalcul d'un lot de publications, à écrire par l'appelant."""

    verdicts: dict[int, RefreshVerdict]
    """Verdict de chaque publication du lot."""
    saved: list[Publication]
    """Publications de verdict `SAVED`, dans leur état recalculé."""


def consolidate(conn: Connection, publication_ids: Sequence[int]) -> Consolidation:
    """Recalcule les métadonnées d'un lot de publications depuis leurs enregistrements sources, sans rien écrire.

    Recalcul complet : lit tous les enregistrements sources rattachés, agrège (`domain.publications.aggregation`), rejoue les corrections nées de l'arbitrage, choisit l'URL du texte intégral (`domain.publications.access`), déduit le statut open access des copies (`domain.publications.open_access`), pose l'éditeur d'après le type corrigé. Rattrape les métadonnées périmées (`ongoing_thesis` → `thesis` après soutenance).

    Une publication absente de la base (`ABSENT`), sans enregistrement source (`NO_SOURCE`), ou de `doc_type` résolu dans `OUT_OF_SCOPE_DOC_TYPES` (`INADMISSIBLE_TYPE`) reste hors de `saved`. Le module du cycle de vie supprime les deux dernières.

    Chaque publication reçoit les données de ses seuls enregistrements sources, de sa revue, de son DOI et de son préfixe. La réconciliation décide quels enregistrements sources forment une même œuvre.
    """
    publications = PublicationStore(conn).find_by_ids(publication_ids)
    verdicts = dict.fromkeys(publication_ids, RefreshVerdict.ABSENT)
    sources = source_records_of(conn, list(publications))
    monograph_ids = sorted(
        {
            s.monograph_id
            for records in sources.values()
            for s in records
            if s.monograph_id is not None
        }
    )
    monograph_serials = monograph_serial_ids(conn, monograph_ids) if monograph_ids else {}

    # L'agrégation part des colonnes corrigées par la phase `metadata_correction`.
    aggregated: dict[int, Publication] = {}
    for publication_id, publication in publications.items():
        records = sources.get(publication_id)
        if not records:
            verdicts[publication_id] = RefreshVerdict.NO_SOURCE
            continue
        _refresh_aggregate(
            publication,
            records,
            source_priority=SOURCE_PRIORITY,
            monograph_serials=_subset(monograph_serials, (r.monograph_id for r in records)),
        )
        aggregated[publication_id] = publication

    serials = serial_facts(
        conn, sorted({p.serial_id for p in aggregated.values() if p.serial_id is not None})
    )
    copies = publication_copies(conn, list(aggregated))
    embargoed = embargoed_publications(conn, list(aggregated))
    dois = sorted({p.doi.value for p in aggregated.values() if p.doi})
    unpaywall = unpaywall_verdicts(conn, dois) if dois else {}
    prefixes = sorted({p.doi.prefix.value for p in aggregated.values() if p.doi})
    prefix_publishers = crossref_prefix_publishers(conn, prefixes) if prefixes else {}

    saved: list[Publication] = []
    for publication_id, publication in aggregated.items():
        serial = serials.get(publication.serial_id) if publication.serial_id is not None else None
        _apply_canonical_doc_type_correction(
            publication, serial_type=serial.serial_type if serial else None
        )
        publication_copies_ = copies.get(publication_id, [])
        publication.best_copy_url = access(
            publication_copies_, doi=str(publication.doi) if publication.doi else None
        ).url
        publication.oa_status = publication_oa_status(
            publication_copies_,
            embargoed=publication_id in embargoed,
            restricted=is_restricted(publication.doc_type, publication.source_extras),
            unpaywall=unpaywall.get(publication.doi.value) if publication.doi else None,
            has_serial=publication.serial_id is not None,
            serial_oa_model=serial.oa_model if serial else None,
        )
        assign_publisher(
            publication,
            sources[publication_id],
            source_priority=SOURCE_PRIORITY,
            prefix_publishers=_subset(
                prefix_publishers, [publication.doi.prefix.value] if publication.doi else []
            ),
        )
        if publication.doc_type in OUT_OF_SCOPE_DOC_TYPES:
            verdicts[publication_id] = RefreshVerdict.INADMISSIBLE_TYPE
            continue
        verdicts[publication_id] = RefreshVerdict.SAVED
        saved.append(publication)
    return Consolidation(verdicts, saved)


def _subset[K, V](mapping: Mapping[K, V], keys: Iterable[K | None]) -> dict[K, V]:
    """Renvoie les entrées de `mapping` des clés `keys` présentes."""
    return {k: mapping[k] for k in keys if k is not None and k in mapping}


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
            title_normalized=publication.title_normalized or "",
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
