"""Copies des publications (`infrastructure.read_models.publications.copies`)."""

from datetime import timedelta

from domain.dates import today
from infrastructure.read_models.publications.copies import publication_copies
from pipeline.ingestion.common.locations import LocationFacts, LocationStore
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record


def test_une_copie_sous_embargo_est_fermee_jusqu_a_sa_date_de_fin(sa_sync_conn):
    publication = insert_publication(sa_sync_conn)
    source_record = insert_source_record(sa_sync_conn, publication, source_id="hal-1")
    LocationStore(sa_sync_conn).replace_locations(
        source_record,
        [
            LocationFacts("https://a.org/ouverte", is_oa=True),
            LocationFacts(
                "https://a.org/levee", is_oa=True, embargo_until=today() - timedelta(days=1)
            ),
            LocationFacts(
                "https://a.org/embargo", is_oa=True, embargo_until=today() + timedelta(days=2)
            ),
        ],
    )

    copies = publication_copies(sa_sync_conn, [publication])[publication]

    assert {c.url: c.is_oa for c in copies} == {
        "https://a.org/ouverte": True,
        "https://a.org/levee": True,
        "https://a.org/embargo": False,
    }
