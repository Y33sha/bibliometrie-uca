"""Lignes APC de la liste des publications : `in_perimeter` suit la règle du filtre `has_apc`."""

from infrastructure.read_models.publications.list import list_publications
from infrastructure.read_models.publications.models import PublicationFilters
from tests.integration.helpers.publications import insert_apc_payment, insert_publication
from tests.integration.helpers.structures import insert_structure


def test_apc_in_perimeter_follows_budget_structure(sa_sync_conn):
    inside = insert_structure(sa_sync_conn, "apc_inside", structure_type="universite")
    outside = insert_structure(sa_sync_conn, "apc_outside", structure_type="universite")
    publication_id = insert_publication(
        sa_sync_conn, "APC", normalize_title=False, doc_type=None, in_perimeter=True
    )
    for budget in (inside, outside, None):
        insert_apc_payment(
            sa_sync_conn,
            publication_id=publication_id,
            amount_eur_ht=100,
            budget_structure_id=budget,
            open_access_fee=True,
        )

    response = list_publications(
        sa_sync_conn,
        filters=PublicationFilters(),
        perimeter_structure_ids=[inside],
        page=1,
        per_page=10,
        sort="year_desc",
    )

    item = next(p for p in response.publications if p.id == publication_id)
    assert item.apc is not None
    assert {a.budget_structure_id: a.in_perimeter for a in item.apc} == {
        inside: True,
        outside: False,
        None: False,
    }
