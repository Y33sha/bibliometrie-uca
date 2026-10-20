"""Oneshot `backfill_initials_split` : une signature au nom réduit à des initiales rejoint l'identité de son découpage corrigé, et la synchronisation qui suit la garde."""

from sqlalchemy import text

from domain.persons.contributor_name import ContributorName
from interfaces.cli.oneshot.backfill_initials_split import backfill
from pipeline.ingestion.common.source_contribution_queries import ContributionsBatchQueries
from pipeline.ingestion.common.source_contributions import AuthorRecord, write_source_contributions
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _source_contribution(conn, raw: str, normalized_name: str) -> tuple[int, int]:
    source_record = insert_source_record(
        conn, source="openalex", source_id="W-initiales", title="t"
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
                "SELECT aik.last_name_normalized, aik.first_name_normalized "
                "FROM source_contributions sa JOIN contributor_information aik ON aik.id = sa.contributor_information_id "
                "WHERE sa.id = :id"
            ),
            {"id": source_contribution_id},
        ).one()
    )


def test_initiales_finales_passent_en_prenom(sa_sync_conn):
    # Identité au découpage du parseur sans la règle des initiales : nom « l », prénom « del buono ».
    _, sa = _source_contribution(sa_sync_conn, "Del Buono L.", "del buono l")

    assert backfill(sa_sync_conn, apply=True) == 1
    assert _split(sa_sync_conn, sa) == ("del buono", "l")


def test_synchronisation_apres_backfill_garde_la_contribution_source(sa_sync_conn):
    source_record, sa = _source_contribution(sa_sync_conn, "Del Buono L.", "del buono l")
    backfill(sa_sync_conn, apply=True)

    write_source_contributions(
        sa_sync_conn,
        ContributionsBatchQueries(),
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
    backfill(sa_sync_conn, apply=True)

    assert backfill(sa_sync_conn, apply=True) == 0
