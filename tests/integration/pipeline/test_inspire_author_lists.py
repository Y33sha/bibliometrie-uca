"""Enregistrements sources OpenAlex sans contributions sources, à la place desquelles valent celles d'INSPIRE-HEP (`pipeline.ingestion.common.inspire_author_lists`). Les commits par lot sont neutralisés."""

import logging

from sqlalchemy import text

from domain.contributions.contribution_roles import ContributionRole
from domain.persons.contributor_name import ContributorName
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from infrastructure.db.queues import Queue
from pipeline.ingestion.common.inspire_author_lists import (
    fetch_author_list_keys,
    withhold_covered_source_contributions,
)
from pipeline.ingestion.common.source_contribution_store import SourceContributionStore
from pipeline.ingestion.common.source_contributions import (
    AuthorRecord,
    write_source_contributions,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_record

_DOI, _CDS, _HAL_ID = (
    SourceIdentifierType.DOI,
    SourceIdentifierType.CDS,
    SourceIdentifierType.HAL_ID,
)
_SECONDARY, _RELATED = SourceIdentifierRole.SECONDARY, SourceIdentifierRole.RELATED
_ARTICLE_DOI, _ERRATUM_DOI = "10.1103/physrevd.108.012021", "10.1103/physrevd.110.019901"


def _inspire(conn) -> int:
    return insert_source_record(
        conn,
        source="inspire",
        source_id="2683002",
        identifiers=[
            SourceIdentifier(_DOI, _ARTICLE_DOI, _SECONDARY),
            SourceIdentifier(_DOI, _ERRATUM_DOI, _RELATED),
            SourceIdentifier(_CDS, "2838028", _SECONDARY),
        ],
    )


def _openalex(conn, source_id: str, identifier: SourceIdentifier, publication=None) -> int:
    """Insère un enregistrement source OpenAlex à deux auteurs, d'empreinte de bloc auteurs « h »."""
    record = insert_source_record(
        conn, publication, source="openalex", source_id=source_id, identifiers=[identifier]
    )
    write_source_contributions(
        SourceContributionStore(conn),
        "openalex",
        record,
        [
            AuthorRecord(0, ContributorName(raw="Dupont, Jean"), roles=[ContributionRole.AUTHOR]),
            AuthorRecord(1, ContributorName(raw="Xu, Z."), roles=[ContributionRole.AUTHOR]),
        ],
    )
    SourceContributionStore(conn).set_authors_hash(record, "h")
    return record


def _authors(conn, record: int) -> tuple[str | None, int, int]:
    """Renvoie l'empreinte du bloc auteurs, le nombre d'auteurs et le nombre de contributions sources de l'enregistrement source."""
    row = conn.execute(
        text("""
            SELECT sr.authors_hash, sr.author_count,
                   (SELECT count(*) FROM source_contributions sc WHERE sc.source_record_id = sr.id)
            FROM source_records sr WHERE sr.id = :id
        """),
        {"id": record},
    ).one()
    return row[0], row[1], row[2]


def test_identifiants_des_enregistrements_sources_inspire_hors_identifiants_lies(sa_sync_conn):
    conn = sa_sync_conn
    _inspire(conn)
    insert_source_record(conn, source="hal", source_id="hal-04174615", doi="10.1/autre")
    assert fetch_author_list_keys(conn) == {(_DOI, _ARTICLE_DOI), (_CDS, "2838028")}


def test_enregistrements_openalex_du_meme_document_sans_contributions_sources(
    sa_sync_conn, monkeypatch
):
    conn = sa_sync_conn
    monkeypatch.setattr(conn, "commit", lambda: None)
    log = logging.getLogger("test")
    _inspire(conn)
    publication = insert_publication(conn)
    article = _openalex(
        conn, "W1", SourceIdentifier(_DOI, _ARTICLE_DOI, SourceIdentifierRole.DERIVED), publication
    )
    cds_copy = _openalex(conn, "W2", SourceIdentifier(_CDS, "2838028", _SECONDARY))
    erratum = _openalex(
        conn, "W3", SourceIdentifier(_DOI, _ERRATUM_DOI, SourceIdentifierRole.DERIVED)
    )
    other = _openalex(conn, "W4", SourceIdentifier(_HAL_ID, "hal-04174615", _SECONDARY))
    clear(conn, Queue.PUBLICATION_CONTRIBUTIONS)

    assert withhold_covered_source_contributions(conn, log) == 4

    assert _authors(conn, article) == (None, 0, 0)
    assert _authors(conn, cds_copy) == (None, 0, 0)
    assert _authors(conn, erratum) == ("h", 2, 2)
    assert _authors(conn, other) == ("h", 2, 2)
    assert queued(conn, Queue.PUBLICATION_CONTRIBUTIONS) == {publication}
    assert withhold_covered_source_contributions(conn, log) == 0
