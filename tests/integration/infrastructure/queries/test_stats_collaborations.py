"""Tests d'intégration des collaborations internationales (`StatsQueries.collaborations`)."""

from infrastructure.read_models.publications.models import PublicationFilters
from infrastructure.read_models.stats.queries import StatsQueries
from tests.integration.helpers.config import set_config
from tests.integration.helpers.publications import insert_publication


def test_counts_foreign_countries_only(sa_sync_conn):
    """Le pays de l'établissement et l'absence de pays (`xx`) ne font pas une collaboration internationale."""
    for countries in (["fr", "de"], ["fr", "xx"], ["fr"]):
        insert_publication(sa_sync_conn, in_perimeter=True, countries=countries)

    res = StatsQueries(sa_sync_conn).collaborations(filters=PublicationFilters())

    assert [(r.code, r.value) for r in res.rows] == [("de", 1)]
    assert res.international_count == 1
    assert res.total_count == 3


def test_institution_country_comes_from_config(sa_sync_conn):
    set_config(sa_sync_conn, "institution_country", "de")
    for countries in (["fr", "de"], ["de"]):
        insert_publication(sa_sync_conn, in_perimeter=True, countries=countries)

    res = StatsQueries(sa_sync_conn).collaborations(filters=PublicationFilters())

    assert [(r.code, r.value) for r in res.rows] == [("fr", 1)]
    assert res.international_count == 1
