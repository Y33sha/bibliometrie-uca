"""Recalcul de l'état consolidé d'une publication depuis ses `source_records`."""

from collections.abc import Sequence
from enum import StrEnum
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.publications.aggregation import refresh_from_sources as _refresh_aggregate
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from domain.source_records.metadata_correction.rules import (
    MetadataForCorrection,
    effective_doc_type_for_publication,
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
    meta: dict[str, JsonValue] | None
    license: str | None


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
        meta=row.meta,
        license=row.license,
    )


# ── Lectures du recalcul ──────────────────────────────────────────────


def source_records_of(conn: Connection, pub_id: int) -> list[SourceRecord]:
    # Le `doi` projeté est la colonne nue ; la substitution Zenodo (concept plutôt que version) est déjà persistée par `metadata_correction`.
    """Les `SourceRecord` attachées à une publication canonique, matière de l'agrégation."""
    result = conn.execute(
        text("""
            SELECT sp.id, sp.source::text AS source, sp.source_id,
                   sp.title, sp.publication_year, sp.doc_type::text AS doc_type,
                   sp.doi,
                   sp.journal_id, sp.monograph_id, sp.container_title, sp.language,
                   sp.oa_status::text AS oa_status, sp.is_retracted, sp.abstract,
                   sp.countries, sp.urls, sp.keywords,
                   sp.topics, sp.biblio, sp.meta, sp.license::text AS license
            FROM source_records sp
            WHERE sp.publication_id = :id
        """),
        {"id": pub_id},
    )
    return [_source_record_from_row(vue) for vue in rows_as(_SourceRecordRow, result)]


def converged_secondary_ids(conn: Connection, pub_id: int) -> frozenset[int]:
    """Ids des `source_records` de `pub_id` dont le DOI a été substitué par une correction de convergence (forme secondaire : version, variante, pièce d'un dataset). L'agrégation les dépriorise pour que les scalaires descriptifs viennent de l'enregistrement canonique."""
    result = conn.execute(
        text(f"""
            SELECT id FROM source_records
            WHERE publication_id = :id
              AND {corrected_by("doi", "source_records")} = ANY(:cases)
        """),
        {"id": pub_id, "cases": list(CONVERGENCE_CASES)},
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


def journal_type_of(conn: Connection, journal_id: int) -> str | None:
    """`journal_type` d'un journal, pour le rejeu des corrections qui dépendent de la revue. None si le journal n'existe pas ou son type n'est pas posé."""
    return conn.execute(
        text("SELECT journal_type::text FROM journals WHERE id = :id"),
        {"id": journal_id},
    ).scalar_one_or_none()


def _refresh_sources(conn: Connection, pub_id: int) -> None:
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
        {"id": pub_id},
    )


class RefreshVerdict(StrEnum):
    """Issue du recalcul d'une publication depuis ses `source_records`."""

    SAVED = "saved"
    ABSENT = "absent"
    NO_SOURCE = "no_source"
    INADMISSIBLE_TYPE = "inadmissible_type"


def refresh_from_sources(conn: Connection, pub_id: int) -> RefreshVerdict:
    """Recalcule les métadonnées canoniques d'une publication depuis ses `source_records`.

    Recalcul complet : lit toutes les sources attachées, agrège (`domain.publications.aggregation`), rejoue les corrections nées de l'arbitrage, persiste. Rattrape les métadonnées périmées (`ongoing_thesis` → `thesis` après soutenance).

    Une publication sans source rattachée (`NO_SOURCE`), ou dont le `doc_type` résolu tombe dans `OUT_OF_SCOPE_DOC_TYPES` (`INADMISSIBLE_TYPE`), reste en l'état. Le module du cycle de vie la supprime sur ce verdict.

    Ne touche que la publication reçue et ses sources : quelles `source_records` forment une même œuvre relève de la réconciliation. Laisse `notes` inchangé.
    """
    store = PublicationStore(conn)
    pub = store.find_by_id(pub_id)
    if pub is None:
        return RefreshVerdict.ABSENT

    sources = source_records_of(conn, pub_id)
    if not sources:
        return RefreshVerdict.NO_SOURCE

    secondary_ids = converged_secondary_ids(conn, pub_id)
    # L'agrégation repart des colonnes déjà corrigées par la phase `metadata_correction`, pas du brut.
    monograph_ids = sorted({s.monograph_id for s in sources if s.monograph_id is not None})
    dois = sorted({doi.value for s in sources if (doi := DOI.try_parse(s.doi)) is not None})
    _refresh_aggregate(
        pub,
        sources,
        source_priority=SOURCE_PRIORITY,
        secondary_ids=secondary_ids,
        monograph_journals=monograph_journal_ids(conn, monograph_ids) if monograph_ids else {},
        unpaywall=unpaywall_verdicts(conn, dois) if dois else {},
    )
    _apply_canonical_doc_type_correction(
        pub,
        journal_type=journal_type_of(conn, pub.journal_id) if pub.journal_id is not None else None,
    )

    if pub.doc_type in OUT_OF_SCOPE_DOC_TYPES:
        return RefreshVerdict.INADMISSIBLE_TYPE

    store.save(pub)
    _refresh_sources(conn, pub_id)
    return RefreshVerdict.SAVED


def _apply_canonical_doc_type_correction(pub: Publication, *, journal_type: str | None) -> None:
    """Rejoue les corrections de `doc_type` sur la publication canonique après l'arbitrage.

    L'arbitrage prend chaque champ de la source la plus prioritaire qui le renseigne : la publication porte alors une combinaison — `doc_type` de l'une, `journal_id` de l'autre — qu'aucune `source_record` ne portait, et qu'aucune correction par source n'a pu voir. Le contrat reçoit les champs que l'agrégation arbitre, dont le `journal_type` du `journal_id` canonique.

    `effective_doc_type_for_publication` écarte les règles lisant un fait propre à un enregistrement source ; les champs correspondants restent nuls ici. L'`oa_status` est hors du rejeu, en entrée comme en sortie — une source corrigée remonte d'elle-même par l'agrégation du statut le plus ouvert, et Unpaywall tranche après vérification.

    `journal_type` est le type de la revue `pub.journal_id`. Mute `pub.doc_type` et trace la règle dans `pub.meta['corrections']['doc_type']`. Idempotent.
    """
    corrected = effective_doc_type_for_publication(
        MetadataForCorrection(
            title=pub.title,
            doc_type=pub.doc_type,
            doi=str(pub.doi) if pub.doi else None,
            journal_id=pub.journal_id,
            oa_status=None,
            urls=None,
            journal_type=journal_type,
            oa_model=None,
            embargo_expired=False,
            self_declared_preprint=False,
            declares_conference=False,
            registrant_publisher_type=None,
        )
    )
    if corrected is not None and corrected.value != pub.doc_type:
        pub.doc_type = corrected.value
        meta = dict(pub.meta or {})
        existing_corrections = meta.get("corrections")
        corrections = dict(existing_corrections) if isinstance(existing_corrections, dict) else {}
        corrections["doc_type"] = corrected.rule.value
        meta["corrections"] = corrections
        pub.meta = meta
