"""Indicateurs de citation de chaque publication (`StatsQueries.citation_points`)."""

from sqlalchemy import text

from infrastructure.read_models.publications.models import PublicationFilters
from infrastructure.read_models.stats.queries import StatsQueries
from tests.integration.helpers.publications import insert_publication


def test_un_point_par_publication_pourvue_d_un_nombre_de_citations(sa_sync_conn):
    impacts = {
        "Cité <i>souvent</i>": '{"cited_by_count": 40, "fwci": 2.5}',
        "Cité sans FWCI": '{"cited_by_count": 3}',
        "Sans indicateur": None,
    }
    for title, impact in impacts.items():
        publication_id = insert_publication(sa_sync_conn, title, in_perimeter=True)
        sa_sync_conn.execute(
            text("UPDATE publications SET impact = CAST(:impact AS jsonb) WHERE id = :id"),
            {"impact": impact, "id": publication_id},
        )

    points = StatsQueries(sa_sync_conn).citation_points(filters=PublicationFilters()).points

    assert {(p.title, p.cited_by_count, p.fwci) for p in points} == {
        ("Cité souvent", 40, 2.5),
        ("Cité sans FWCI", 3, None),
    }
