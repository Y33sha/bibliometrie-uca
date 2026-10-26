"""Organisations partenaires d'une structure, et filtre des publications par organisation partenaire."""

from sqlalchemy import text

from infrastructure.read_models.entity_labels.queries import entity_label
from infrastructure.read_models.publications.models import PublicationFilters
from infrastructure.read_models.structures.queries import StructuresQueries
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.read_models import publications_queries
from tests.integration.helpers.rors import insert_author, insert_ror_tree, refresh_publication_rors
from tests.integration.helpers.structures import add_source_contribution_structure, insert_structure


def _copublication(conn) -> tuple[int, int]:
    """Une publication d'un laboratoire du périmètre (ROR `0lab00001`) avec un laboratoire allemand. Rend la structure et la publication."""
    insert_ror_tree(conn)
    structure = insert_structure(conn, "LAB", name="Laboratoire")
    conn.execute(
        text("UPDATE structures SET ror_id = '0lab00001' WHERE id = :id"), {"id": structure}
    )
    publication = insert_publication(conn, publication_year=2024)
    person = insert_person(conn, "Dupont")
    own = insert_author(conn, publication, "W1", "0lab00001", person=person)
    add_source_contribution_structure(conn, own, structure)
    insert_author(conn, publication, "W2", "0ger00001")
    refresh_publication_rors(conn)
    return structure, publication


def _partners(conn, structure: int, **filters):
    params = {"years": [], "countries": [], "types": [], **filters}
    return StructuresQueries(conn).get_structure_partners(structure, page=1, per_page=50, **params)


def test_les_partenaires_excluent_la_structure_et_ses_ancetres(sa_sync_conn):
    structure, _ = _copublication(sa_sync_conn)
    result = _partners(sa_sync_conn, structure)
    assert [(p.ror_id, p.country_code, p.publications) for p in result.partners] == [
        ("0ger00001", "de", 1)
    ]
    assert [(o.value, o.count) for o in result.types] == [("facility", 1)]


def test_filtre_par_pays_et_par_annee(sa_sync_conn):
    structure, _ = _copublication(sa_sync_conn)
    assert _partners(sa_sync_conn, structure, countries=["fr"]).total == 0
    assert _partners(sa_sync_conn, structure, years=[2023]).total == 0
    assert _partners(sa_sync_conn, structure, years=[2024]).total == 1
    assert [(o.value, o.count) for o in _partners(sa_sync_conn, structure, years=[2023]).years] == [
        ("2024", 1)
    ]


def test_les_publications_se_filtrent_par_organisation_partenaire(sa_sync_conn):
    """Un établissement retrouve les publications de ses laboratoires."""
    structure, publication = _copublication(sa_sync_conn)
    for ror, expected in (("0univ0001", [publication]), ("0ger00001", [publication])):
        page = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(lab_ids=[structure], partner_rors=[ror]),
            page=1,
            per_page=10,
            sort="year_desc",
        )
        assert [p.id for p in page.publications] == expected


def test_libelle_d_une_organisation_partenaire(sa_sync_conn):
    insert_ror_tree(sa_sync_conn)
    assert entity_label(sa_sync_conn, kind="partner", entity_id="0ger00001") == "Labor"
    assert entity_label(sa_sync_conn, kind="serial", entity_id="0ger00001") is None
