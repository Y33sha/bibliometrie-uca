"""Tests d'intégration pour `infrastructure.read_models.persons.detail`."""

from functools import partial

from sqlalchemy import text

from infrastructure.read_models.addresses.queries import AddressesQueries
from infrastructure.read_models.persons.queries import PersonsQueries
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import insert_structure

# Contribution du périmètre.
_in_perimeter_contribution = partial(insert_contribution, in_perimeter=True)


def _source_contribution(conn, publication_id, *, source="hal", roles=None):
    """Insère une contribution source sur un enregistrement source de la publication, d'identifiant source unique."""
    source_record_id = insert_source_record(
        conn, publication_id, source=source, source_id=f"detail-{publication_id}-{source}"
    )
    return insert_source_contribution(
        conn, source_record_id, source=source, roles=roles
    ), source_record_id


def _join_contribution(conn, source_contribution, *, publication_id, person_id):
    """Ajoute la contribution source `(id, enregistrement source)` à la contribution de la personne dans la publication."""
    source_contribution_id, source_record_id = source_contribution
    conn.execute(
        text("""
            INSERT INTO aligned_source_contributions
                (source_contribution_id, contribution_id, source_record_id, method)
            SELECT :sc, g.id, :sr, 'reference'
            FROM contributions g
            WHERE g.publication_id = :p AND g.person_id = :person
        """),
        {
            "sc": source_contribution_id,
            "sr": source_record_id,
            "p": publication_id,
            "person": person_id,
        },
    )


def _theses(conn, person_id):
    return [
        thesis
        for section in PersonsQueries(conn).person_theses(person_id).sections
        for thesis in section.theses
    ]


class TestPersonTheses:
    def test_author_name_matches_author_person_id(self, sa_sync_conn):
        """Deux doctorants sur la thèse : le nom d'auteur affiché est celui de la personne `author_person_id`."""
        jury = insert_person(sa_sync_conn, "Jury", first_name="Jean")
        alice = insert_person(sa_sync_conn, "Doctorant", first_name="Alice")
        bruno = insert_person(sa_sync_conn, "Doctorant", first_name="Bruno")
        publication = insert_publication(sa_sync_conn, doc_type="thesis")
        _in_perimeter_contribution(sa_sync_conn, publication, person_id=jury, roles=["jury_member"])
        _in_perimeter_contribution(sa_sync_conn, publication, person_id=alice, roles=["author"])
        _in_perimeter_contribution(sa_sync_conn, publication, person_id=bruno, roles=["author"])

        theses = _theses(sa_sync_conn, jury)

        assert len(theses) == 1
        thesis = theses[0]
        expected = {alice: "Alice Doctorant", bruno: "Bruno Doctorant"}
        assert thesis.author_name == expected[thesis.author_person_id]

    def test_these_soutenue_ailleurs_et_ouvrage_dirige(self, sa_sync_conn):
        """Une thèse sans enregistrement source theses.fr figure parmi les thèses de son rapporteur ; un ouvrage dont la personne est éditrice n'y figure pas."""
        person = insert_person(sa_sync_conn, "Rapporteur")
        these = insert_publication(sa_sync_conn, "Thèse soutenue ailleurs", doc_type="thesis")
        ouvrage = insert_publication(sa_sync_conn, "Ouvrage dirigé", doc_type="book")
        insert_contribution(sa_sync_conn, these, person_id=person, roles=["rapporteur"])
        insert_contribution(sa_sync_conn, ouvrage, person_id=person, roles=["editor"])

        assert [thesis.title for thesis in _theses(sa_sync_conn, person)] == [
            "Thèse soutenue ailleurs"
        ]


class TestMemberReads:
    """Les lectures d'affichage passent par les contributions sources des contributions de la personne."""

    def test_theses_count_counts_member_non_author_theses(self, sa_sync_conn):
        person = insert_person(sa_sync_conn, "Directrice")
        thesis = insert_publication(sa_sync_conn, doc_type="thesis")
        insert_contribution(sa_sync_conn, thesis, person_id=person, roles=["thesis_director"])
        member = _source_contribution(
            sa_sync_conn, thesis, source="theses", roles=["thesis_director"]
        )
        _join_contribution(sa_sync_conn, member, publication_id=thesis, person_id=person)

        profile = PersonsQueries(sa_sync_conn).person_profile(person)

        assert profile is not None
        assert profile.theses_count == 1

    def test_addresses_come_from_aligned_source_contributions(self, sa_sync_conn):
        """L'adresse d'une contribution source de la contribution figure ; celle d'une contribution source hors des contributions de la personne, non."""
        person = insert_person(sa_sync_conn, "Adressee")
        publication = insert_publication(sa_sync_conn)
        other_publication = insert_publication(sa_sync_conn)
        insert_contribution(sa_sync_conn, publication, person_id=person, roles=["author"])
        member = _source_contribution(sa_sync_conn, publication)
        _join_contribution(sa_sync_conn, member, publication_id=publication, person_id=person)
        outsider, _ = _source_contribution(sa_sync_conn, other_publication)
        member_address = insert_address(sa_sync_conn, "Membre de la contribution")
        insert_source_contribution_address(sa_sync_conn, member[0], address_id=member_address)
        insert_source_contribution_address(
            sa_sync_conn, outsider, address_id=insert_address(sa_sync_conn, "Hors contribution")
        )

        response = PersonsQueries(sa_sync_conn).person_addresses(
            person, year=None, page=1, per_page=50
        )

        assert [address.id for address in response.addresses] == [member_address]


class TestAddressesByYear:
    """Adresses de la personne sur les publications d'une année : CHU sur deux publications de 2024 et une de 2023, UCA sur une de 2024, une publication de 2024 sans adresse."""

    def _setup(self, conn):
        person = insert_person(conn, "Adressee")
        chu = insert_structure(conn, "TEST-CHU", acronym="CHU")
        uca = insert_structure(conn, "TEST-UCA", acronym="UCA")
        rejected = insert_structure(conn, "TEST-REJ", acronym="REJ")
        chu_address = insert_address(conn, "CHU Clermont-Ferrand")
        uca_address = insert_address(conn, "Université Clermont Auvergne, CHU")
        insert_address_structure(conn, chu_address, structure_id=chu)
        insert_address_structure(conn, uca_address, structure_id=uca)
        insert_address_structure(conn, uca_address, structure_id=chu, is_confirmed=True)
        insert_address_structure(conn, uca_address, structure_id=rejected, is_confirmed=False)
        publications = {}
        for key, year, addresses in (
            ("a", 2024, [chu_address, uca_address]),
            ("b", 2024, [chu_address]),
            ("c", 2024, []),
            ("old", 2023, [chu_address]),
        ):
            publication = insert_publication(conn, publication_year=year)
            publications[key] = publication
            insert_contribution(conn, publication, person_id=person, roles=["author"])
            member = _source_contribution(conn, publication)
            _join_contribution(conn, member, publication_id=publication, person_id=person)
            for address in addresses:
                insert_source_contribution_address(conn, member[0], address_id=address)
        # Un coauteur d'une autre publication de 2024 porte aussi l'adresse du CHU.
        other_person = insert_person(conn, "Coauteur")
        other_publication = insert_publication(conn, publication_year=2024)
        insert_contribution(conn, other_publication, person_id=other_person, roles=["author"])
        other = _source_contribution(conn, other_publication)
        _join_contribution(conn, other, publication_id=other_publication, person_id=other_person)
        insert_source_contribution_address(conn, other[0], address_id=chu_address)
        return person, publications, {"chu": chu, "uca": uca}, chu_address, uca_address

    def test_addresses_sorted_by_publication_count(self, sa_sync_conn):
        person, _, _, chu_address, uca_address = self._setup(sa_sync_conn)

        response = PersonsQueries(sa_sync_conn).person_addresses(
            person, year=2024, page=1, per_page=50
        )

        assert [(a.id, a.publication_count) for a in response.addresses] == [
            (chu_address, 2),
            (uca_address, 1),
        ]

    def test_summary_counts_publications_per_structure(self, sa_sync_conn):
        """Le dénominateur compte les publications ; le lien rejeté n'est pas compté ; le CHU, présent dans les deux adresses de la publication a, compte une fois pour elle."""
        person, _, structures, _, _ = self._setup(sa_sync_conn)

        summary = PersonsQueries(sa_sync_conn).person_address_summary(person, year=2024)

        assert (summary.first_year, summary.last_year) == (2023, 2024)
        assert (summary.publications, summary.publications_with_address) == (3, 2)
        assert [(s.id, s.publications) for s in summary.structures] == [
            (structures["chu"], 2),
            (structures["uca"], 1),
        ]

    def test_address_publications_restricted_to_person_and_year(self, sa_sync_conn):
        person, publications, _, chu_address, _ = self._setup(sa_sync_conn)

        items = AddressesQueries(sa_sync_conn).get_address_publications(
            chu_address, 20, person_id=person, year=2024
        )

        assert {p.id for p in items} == {publications["a"], publications["b"]}
