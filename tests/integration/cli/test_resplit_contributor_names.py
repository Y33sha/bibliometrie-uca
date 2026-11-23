"""Script de maintenance `resplit_contributor_names` : une contribution source rejoint les informations du contributeur de son découpage corrigé, et la synchronisation qui suit la garde."""

from sqlalchemy import text

from domain.persons.contributor_name import ContributorName
from interfaces.cli.maintenance.resplit_contributor_names import resplit
from pipeline.ingestion.common.source_contribution_store import SourceContributionStore
from pipeline.ingestion.common.source_contributions import AuthorRecord, write_source_contributions
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _source_contribution(conn, raw: str, normalized_name: str) -> tuple[int, int]:
    source_record = insert_source_record(
        conn, source="openalex", source_id="W-decoupage", title="t"
    )
    sa = insert_source_contribution(
        conn,
        source_record,
        source="openalex",
        raw_author_name=raw,
        author_name_normalized=normalized_name,
    )
    return source_record, sa


def _split(conn, source_contribution_id: int):
    return tuple(
        conn.execute(
            text(
                "SELECT ci.last_name_normalized, ci.first_name_normalized "
                "FROM source_contributions sc JOIN contributor_information ci ON ci.id = sc.contributor_information_id "
                "WHERE sc.id = :id"
            ),
            {"id": source_contribution_id},
        ).one()
    )


def test_initiales_finales_passent_en_prenom(sa_sync_conn):
    # Informations du contributeur au découpage du parseur sans la règle des initiales : nom « l », prénom « del buono ».
    _, sa = _source_contribution(sa_sync_conn, "Del Buono L.", "del buono l")

    assert resplit(sa_sync_conn, apply=True) == 1
    assert _split(sa_sync_conn, sa) == ("del buono", "l")


def test_segment_entre_parentheses_retire(sa_sync_conn):
    # Informations du contributeur au découpage sans la règle des parenthèses : prénom « christophe author ».
    _, sa = _source_contribution(
        sa_sync_conn, "Corona, Christophe (author)", "christophe author corona"
    )

    assert resplit(sa_sync_conn, apply=True) == 1
    assert _split(sa_sync_conn, sa) == ("corona", "christophe")


def test_synchronisation_apres_resplit_garde_la_contribution_source(sa_sync_conn):
    source_record, sa = _source_contribution(sa_sync_conn, "Del Buono L.", "del buono l")
    resplit(sa_sync_conn, apply=True)

    write_source_contributions(
        SourceContributionStore(sa_sync_conn),
        "openalex",
        source_record,
        [AuthorRecord(0, ContributorName(raw="Del Buono L."))],
    )

    ids = (
        sa_sync_conn.execute(
            text("SELECT id FROM source_contributions WHERE source_record_id = :sp"),
            {"sp": source_record},
        )
        .scalars()
        .all()
    )
    assert ids == [sa]


def test_idempotent(sa_sync_conn):
    _source_contribution(sa_sync_conn, "Del Buono L.", "del buono l")
    resplit(sa_sync_conn, apply=True)

    assert resplit(sa_sync_conn, apply=True) == 0
