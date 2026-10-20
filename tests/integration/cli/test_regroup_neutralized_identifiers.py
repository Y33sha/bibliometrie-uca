"""Oneshot `regroup_neutralized_identifiers` : publications à regrouper après la lecture des identifiants neutralisés."""

from sqlalchemy import text

from interfaces.cli.oneshot.regroup_neutralized_identifiers import mark
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _publication(conn, *, source_records, neutralized):
    """Publication de `enregistrements sources` enregistrements sources, non marquée ; sa première enregistrement source a une contribution source d'ORCID neutralisé si `neutralized`."""
    publication = insert_publication(conn)
    conn.execute(
        text("UPDATE publications SET contributions_dirty = false WHERE id = :p"),
        {"p": publication},
    )
    for rank in range(source_records):
        source_record = insert_source_record(
            conn, publication, source="crossref", source_id=f"c-{publication}-{rank}"
        )
        insert_source_contribution(
            conn,
            source_record,
            source="crossref",
            author_name_normalized="jean dupont",
            identifiers={"orcid": "0000-0001-2345-6789"},
            neutralized_identifiers={"orcid": "shared"} if neutralized and rank == 0 else None,
        )
    return publication


def _dirty(conn, publication):
    return conn.execute(
        text("SELECT contributions_dirty FROM publications WHERE id = :p"), {"p": publication}
    ).scalar_one()


def test_seules_les_publications_a_plusieurs_enregistrements_sources_et_identifiant_neutralise_sont_marquees(
    sa_sync_conn,
):
    visee = _publication(sa_sync_conn, source_records=2, neutralized=True)
    single_source_record = _publication(sa_sync_conn, source_records=1, neutralized=True)
    sans_neutralisation = _publication(sa_sync_conn, source_records=2, neutralized=False)

    mark(sa_sync_conn)

    assert (
        _dirty(sa_sync_conn, visee),
        _dirty(sa_sync_conn, single_source_record),
        _dirty(sa_sync_conn, sans_neutralisation),
    ) == (True, False, False)
