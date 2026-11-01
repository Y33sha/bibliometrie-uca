"""Indicateurs de citation de chaque publication (`StatsQueries.citation_points`)."""

from sqlalchemy import text

from infrastructure.read_models.publications.models import PublicationFilters
from infrastructure.read_models.stats.queries import StatsQueries
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_serial


def test_un_point_par_publication_pourvue_d_un_nombre_de_citations(sa_sync_conn):
    serial_id = insert_serial(sa_sync_conn, "Revue de test")
    impacts = {
        "Cité <i>souvent</i>": ('{"cited_by_count": 40, "fwci": 2.5}', serial_id),
        "Cité sans FWCI": ('{"cited_by_count": 3}', None),
        "Sans indicateur": (None, None),
    }
    for title, (impact, serial) in impacts.items():
        publication_id = insert_publication(sa_sync_conn, title, in_perimeter=True)
        sa_sync_conn.execute(
            text(
                "UPDATE publications SET impact = CAST(:impact AS jsonb), serial_id = :serial"
                " WHERE id = :id"
            ),
            {"impact": impact, "serial": serial, "id": publication_id},
        )

    points = StatsQueries(sa_sync_conn).citation_points(filters=PublicationFilters()).points

    assert {(p.title, p.serial, p.cited_by_count, p.fwci) for p in points} == {
        ("Cité souvent", "Revue de test", 40, 2.5),
        ("Cité sans FWCI", None, 3, None),
    }
