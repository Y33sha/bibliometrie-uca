"""Copies des publications (`infrastructure.read_models.publications.copies`)."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from domain.dates import today
from infrastructure.read_models.publications.copies import publication_copies
from pipeline.ingestion.common.embargoes import Embargo, EmbargoStore
from pipeline.ingestion.common.locations import LocationFacts, LocationStore
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record


@pytest.mark.parametrize(
    ("embargo", "file_open"),
    [
        (None, True),
        (Embargo(today() - timedelta(days=1)), True),
        (Embargo(today() + timedelta(days=2)), False),
        (Embargo(None), False),
    ],
)
def test_le_fichier_depose_est_ferme_jusqu_a_la_fin_de_l_embargo(sa_sync_conn, embargo, file_open):
    publication = insert_publication(sa_sync_conn)
    source_record = insert_source_record(sa_sync_conn, publication, source_id="hal-1")
    LocationStore(sa_sync_conn).replace_locations(
        source_record,
        [
            LocationFacts(
                "https://hal.science/hal-01607327",
                pdf_url="https://hal.science/hal-01607327/document",
                is_oa=True,
            ),
            LocationFacts("https://arxiv.org/abs/2401.00001", is_oa=True),
        ],
    )
    EmbargoStore(sa_sync_conn).replace_embargo(source_record, embargo)

    copies = publication_copies(sa_sync_conn, [publication])[publication]

    # L'embargo vise le fichier déposé ; la copie arXiv reste ouverte.
    assert {c.url: c.is_oa for c in copies} == {
        "https://hal.science/hal-01607327": file_open,
        "https://arxiv.org/abs/2401.00001": True,
    }


@pytest.mark.parametrize(
    ("registered_url", "copy_urls"),
    [
        ("https://e.org/a.pdf", ["https://e.org/a.pdf"]),
        ("https://e.org/article/1", []),
        (None, []),
    ],
)
def test_l_adresse_enregistree_d_un_pdf_donne_une_copie(sa_sync_conn, registered_url, copy_urls):
    """Une publication sans enregistrement source à localisation reçoit la copie de son DOI, en majuscules ou non."""
    publication = insert_publication(sa_sync_conn, doi="10.9/ABC")
    sa_sync_conn.execute(
        text(
            "INSERT INTO dois (doi, registered_url, resolved_at) VALUES ('10.9/abc', :url, now())"
        ),
        {"url": registered_url},
    )

    copies = publication_copies(sa_sync_conn, [publication]).get(publication, [])

    assert [c.url for c in copies] == copy_urls
