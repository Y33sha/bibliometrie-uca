"""Lecture des données de composition des lots du moissonnage par personne : publications sur les années du moissonnage, unité actuelle."""

from pipeline.ingestion.common.person_batches import read_batching_inputs
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_hr_period, insert_person
from tests.integration.helpers.publications import insert_publication


def test_publications_des_annees_du_moissonnage_et_unite_actuelle(sa_sync_conn):
    conn = sa_sync_conn
    a = insert_person(conn, "A")
    b = insert_person(conn, "B")
    insert_hr_period(conn, a, unit_label="Unité A")
    in_window = insert_publication(conn, "t1", publication_year=2024)
    out_of_window = insert_publication(conn, "t2", publication_year=2019)
    insert_contribution(conn, in_window, person_id=a)
    insert_contribution(conn, out_of_window, person_id=a)

    publications, units = read_batching_inputs(conn, [a, b], (2023, 2025))

    assert publications == {a: frozenset({in_window}), b: frozenset()}
    assert units == {a: "Unité A", b: None}
