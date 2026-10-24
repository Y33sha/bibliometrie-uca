"""Recalcul de l'état consolidé d'une publication depuis ses `source_records`."""

from collections.abc import Sequence
from enum import StrEnum
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.publications.aggregation import (
    assign_publisher,
    refresh_from_sources as _refresh_aggregate,
)
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from domain.source_records.corrections import stash_entry
from domain.source_records.metadata_correction.rules import (
    MetadataForCorrection,
    effective_metadata,
)
from domain.source_records.metadata_correction.shared_doi import CONVERGENCE_CASES
from domain.source_records.source_record import SourceRecord
from domain.sources.registry import SOURCE_PRIORITY
from domain.types import JsonValue
from infrastructure.db.rows import rows_as
from infrastructure.sql_fragments import corrected_by
from pipeline.transformation.publications.store import PublicationStore


class _SourceRecordRow(NamedTuple):
    """Projection SQL `get_source_records` : colonnes de `source_records` consommées par l'agrégation canonique (`refresh_from_sources` côté domain)."""

    id: int
    source: str
    source_id: str
    title: str
    publication_year: int | None
    doc_type: str | None
    doi: str | None
    journal_id: int | None
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


def _source_record_from_row(row: _SourceRecordRow) -> SourceRecord:
    """Mapping d'une row SQL `source_records` ⨝ `journals` vers la vue de lecture. Convertit les `text[]` Postgres en tuples immutables."""
    return SourceRecord(
        id=row.id,
        source=row.source,
        source_id=row.source_id,
        title=row.title,
        publication_year=row.publication_year,
        doc_type=row.doc_type,
        doi=row.doi,
        journal_id=row.journal_id,
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


# ── Lectures du recalcul ──────────────────────────────────────────────


def source_records_of(conn: Connection, publication_id: int) -> list[SourceRecord]:
    # Le `doi` projeté est la colonne nue ; la substitution Zenodo (concept plutôt que version) est déjà persistée par `metadata_correction`.
    """Les `SourceRecord` attachées à une publication canonique, matière de l'agrégation."""
    result = conn.execute(
        text("""
            SELECT sr.id, sr.source::text AS source, sr.source_id,
                   sr.title, sr.publication_year, sr.doc_type::text AS doc_type,
                   sr.doi,
                   sr.journal_id, sr.monograph_id, sr.container_title, sr.language,
                   sr.oa_status::text AS oa_status, sr.is_retracted, sr.abstract,
                   sr.countries, sr.urls, sr.keywords,
                   sr.topics, sr.biblio, sr.source_extras, sr.license::text AS license,
                   sr.publisher_id
            FROM source_records sr
            WHERE sr.publication_id = :id
        """),
        {"id": publication_id},
    )
    return [_source_record_from_row(row) for row in rows_as(_SourceRecordRow, result)]


def converged_secondary_ids(conn: Connection, publication_id: int) -> frozenset[int]:
    """Ids des `source_records` de `publication_id` dont le DOI a été substitué par une correction de convergence (forme secondaire : version, variante, pièce d'un dataset). L'agrégation les dépriorise pour que les scalaires descriptifs viennent de l'enregistrement canonique."""
    result = conn.execute(
        text(f"""
            SELECT id FROM source_records
            WHERE publication_id = :id
              AND {corrected_by("doi", "source_records")} = ANY(:cases)
        """),
        {"id": publication_id, "cases": list(CONVERGENCE_CASES)},
    )
    return frozenset(row.id for row in result)


def monograph_journal_ids(conn: Connection, monograph_ids: Sequence[int]) -> dict[int, int | None]:
    """`journal_id` de chaque monographie : sa collection, pour l'agrégation."""
    rows = conn.execute(
        text("SELECT id, journal_id FROM monographs WHERE id = ANY(:ids)"),
        {"ids": list(monograph_ids)},
    )
    return {r.id: r.journal_id for r in rows}


def unpaywall_verdicts(conn: Connection, dois: Sequence[str]) -> dict[str, str]:
    """Verdict d'Unpaywall de chaque DOI que connaît Unpaywall, pour l'agrégation."""
    rows = conn.execute(
        text(
            "SELECT doi, oa_status::text AS oa_status FROM unpaywall"
            " WHERE doi = ANY(:dois) AND oa_status IS NOT NULL"
        ),
        {"dois": list(dois)},
    )
    return {r.doi: r.oa_status for r in rows}


def crossref_prefix_publishers(conn: Connection, prefixes: Sequence[str]) -> dict[str, int]:
    """Titulaire de chaque préfixe DOI Crossref connu, pour l'éditeur des publications."""
    rows = conn.execute(
        text(
            "SELECT prefix, publisher_id FROM doi_prefixes"
            " WHERE prefix = ANY(:prefixes) AND ra = 'Crossref' AND publisher_id IS NOT NULL"
        ),
        {"prefixes": list(prefixes)},
    )
    return {r.prefix: r.publisher_id for r in rows}


def journal_type_of(conn: Connection, journal_id: int) -> str | None:
    """`journal_type` d'un journal, pour le rejeu des corrections qui dépendent de la revue. None si le journal n'existe pas ou son type n'est pas posé."""
    return conn.execute(
        text("SELECT journal_type::text FROM journals WHERE id = :id"),
        {"id": journal_id},
    ).scalar_one_or_none()


def _refresh_sources(conn: Connection, publication_id: int) -> None:
    """Recalcule `publications.sources` par agrégation des `source_records` rattachées."""
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
    """Recalcule les métadonnées canoniques d'une publication depuis ses `source_records`.

    Recalcul complet : lit toutes les sources attachées, agrège (`domain.publications.aggregation`), rejoue les corrections nées de l'arbitrage, pose l'éditeur d'après le type corrigé, persiste. Rattrape les métadonnées périmées (`ongoing_thesis` → `thesis` après soutenance).

    Une publication sans source rattachée (`NO_SOURCE`), ou dont le `doc_type` résolu tombe dans `OUT_OF_SCOPE_DOC_TYPES` (`INADMISSIBLE_TYPE`), reste en l'état. Le module du cycle de vie la supprime sur ce verdict.

    Ne touche que la publication reçue et ses sources : quelles `source_records` forment une même œuvre relève de la réconciliation. Laisse `notes` inchangé.
    """
    store = PublicationStore(conn)
    publication = store.find_by_id(publication_id)
    if publication is None:
        return RefreshVerdict.ABSENT

    sources = source_records_of(conn, publication_id)
    if not sources:
        return RefreshVerdict.NO_SOURCE

    secondary_ids = converged_secondary_ids(conn, publication_id)
    # L'agrégation repart des colonnes déjà corrigées par la phase `metadata_correction`, pas du brut.
    monograph_ids = sorted({s.monograph_id for s in sources if s.monograph_id is not None})
    dois = sorted({doi.value for s in sources if (doi := DOI.try_parse(s.doi)) is not None})
    _refresh_aggregate(
        publication,
        sources,
        source_priority=SOURCE_PRIORITY,
        secondary_ids=secondary_ids,
        monograph_journals=monograph_journal_ids(conn, monograph_ids) if monograph_ids else {},
        unpaywall=unpaywall_verdicts(conn, dois) if dois else {},
    )
    _apply_canonical_doc_type_correction(
        publication,
        journal_type=journal_type_of(conn, publication.journal_id)
        if publication.journal_id is not None
        else None,
    )
    prefixes = [publication.doi.prefix.value] if publication.doi else []
    assign_publisher(
        publication,
        sources,
        source_priority=SOURCE_PRIORITY,
        secondary_ids=secondary_ids,
        prefix_publishers=crossref_prefix_publishers(conn, prefixes) if prefixes else {},
    )

    if publication.doc_type in OUT_OF_SCOPE_DOC_TYPES:
        return RefreshVerdict.INADMISSIBLE_TYPE

    store.save(publication)
    _refresh_sources(conn, publication_id)
    return RefreshVerdict.SAVED


def _apply_canonical_doc_type_correction(
    publication: Publication, *, journal_type: str | None
) -> None:
    """Rejoue les corrections de `doc_type` sur la publication canonique après l'arbitrage.

    L'arbitrage prend chaque champ de la source la plus prioritaire qui le renseigne : la publication réunit alors un `doc_type` d'une source et un `journal_id` d'une autre, combinaison qu'aucune correction par source n'a vue.

    `journal_type` est le type de la revue `publication.journal_id`. Mute `publication.doc_type` et réécrit `publication.corrections` : le type arbitré et la règle, ou rien sans correction. Idempotent.
    """
    corrected = effective_metadata(
        MetadataForCorrection.for_publication(
            title=publication.title,
            doc_type=publication.doc_type,
            doi=str(publication.doi) if publication.doi else None,
            journal_id=publication.journal_id,
            journal_type=journal_type,
        )
    ).doc_type
    publication.corrections = {}
    if corrected is not None and corrected.value != publication.doc_type:
        publication.corrections = {
            "doc_type": stash_entry(publication.doc_type, corrected.rule.value)
        }
        publication.doc_type = corrected.value
