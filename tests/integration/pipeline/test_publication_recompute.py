"""Recalculs ciblés de publications après une fusion manuelle (`PublicationRecompute`)."""

from sqlalchemy import text

from pipeline.public import PublicationRecompute
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _seed_publication(conn) -> int:
    return PublicationStore(conn).create(
        title="T",
        title_normalized="t",
        doc_type="article",
        publication_year=2024,
        doi=None,
        oa_status="unknown",
    )


def test_realign_gives_contributions_their_perimeter_evidence(sa_sync_conn):
    """La contribution d'une contribution source du périmètre est du périmètre dès le recalcul."""
    conn = sa_sync_conn
    publication = _seed_publication(conn)
    source_record = insert_source_record(
        conn, publication, source="hal", source_id="hal-1", title="T", publication_year=2024
    )
    insert_source_contribution(
        conn, source_record, raw_last_name="Martin", raw_first_name="Anne", in_perimeter=True
    )

    PublicationRecompute(conn).realign(publication)

    in_perimeter = conn.execute(
        text("SELECT in_perimeter FROM contributions WHERE publication_id = :id"),
        {"id": publication},
    ).scalar_one()
    assert in_perimeter is True


def test_reconcile_returns_the_kept_publications(sa_sync_conn):
    conn = sa_sync_conn
    publication = _seed_publication(conn)
    source_record = insert_source_record(
        conn, publication, source="hal", source_id="hal-1", title="T", publication_year=2024
    )

    assert PublicationRecompute(conn).reconcile([source_record]) == {publication}
