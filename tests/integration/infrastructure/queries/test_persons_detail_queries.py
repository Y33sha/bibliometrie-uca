"""Tests d'intégration pour `infrastructure.read_models.persons.detail`."""

from functools import partial

from infrastructure.read_models.addresses.queries import AddressesQueries
from infrastructure.read_models.addresses.scoped import person_scope
from infrastructure.read_models.persons.queries import PersonsQueries
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_aligned_source_contribution,
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import insert_structure

# Contribution du périmètre.
_in_perimeter_contribution = partial(insert_contribution, in_perimeter=True)


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
        insert_aligned_source_contribution(
            sa_sync_conn, thesis, person, source="theses", roles=["thesis_director"]
        )

        profile = PersonsQueries(sa_sync_conn).person_profile(person)

        assert profile is not None
        assert profile.theses_count == 1

    def test_addresses_come_from_aligned_source_contributions(self, sa_sync_conn):
        """L'adresse d'une contribution source de la contribution figure ; celle d'une contribution source hors des contributions de la personne, non."""
        person = insert_person(sa_sync_conn, "Adressee")
        publication = insert_publication(sa_sync_conn)
        other_publication = insert_publication(sa_sync_conn)
        insert_contribution(sa_sync_conn, publication, person_id=person, roles=["author"])
        member = insert_aligned_source_contribution(sa_sync_conn, publication, person)
        outsider = insert_source_contribution(
            sa_sync_conn,
            insert_source_record(
                sa_sync_conn, other_publication, source="openalex", source_id="outsider"
            ),
        )
        member_address = insert_address(sa_sync_conn, "Membre de la contribution")
        insert_source_contribution_address(sa_sync_conn, member, address_id=member_address)
        insert_source_contribution_address(
            sa_sync_conn, outsider, address_id=insert_address(sa_sync_conn, "Hors contribution")
        )

        response = PersonsQueries(sa_sync_conn).person_addresses(person, page=1, per_page=50)

        assert [address.id for address in response.addresses] == [member_address]

    def test_profile_signals_addresses(self, sa_sync_conn):
        """Le profil signale des adresses pour la personne qui en a, aucune pour une personne sans publication."""
        person = insert_person(sa_sync_conn, "Adressee")
        publication = insert_publication(sa_sync_conn)
        insert_contribution(sa_sync_conn, publication, person_id=person, roles=["author"])
        member = insert_aligned_source_contribution(sa_sync_conn, publication, person)
        insert_source_contribution_address(
            sa_sync_conn, member, address_id=insert_address(sa_sync_conn, "Adresse brute")
        )
        queries = PersonsQueries(sa_sync_conn)

        with_address = queries.person_profile(person)
        without_address = queries.person_profile(insert_person(sa_sync_conn, "Sansadresse"))

        assert with_address is not None
        assert without_address is not None
        assert with_address.has_addresses is True
        assert without_address.has_addresses is False

    def test_addresses_are_raw_addresses_only(self, sa_sync_conn):
        """Un libellé HAL, un nom seul ou une adresse sans origine sont absents des adresses et du compte des publications avec adresse."""
        person = insert_person(sa_sync_conn, "Adressee")
        texts_by_publication = (
            [
                ("Institut Pascal, Aubière, France", "raw"),
                ("IP - Institut Pascal (Aubière - France)", "hal_label"),
            ],
            [("Institut Pascal", "name_only"), ("Adresse à classer", None)],
        )
        raw_address = None
        for texts in texts_by_publication:
            publication = insert_publication(sa_sync_conn)
            insert_contribution(sa_sync_conn, publication, person_id=person, roles=["author"])
            member = insert_aligned_source_contribution(sa_sync_conn, publication, person)
            for raw_text, origin in texts:
                address = insert_address(sa_sync_conn, raw_text, origin=origin)
                insert_source_contribution_address(sa_sync_conn, member, address_id=address)
                if origin == "raw":
                    raw_address = address
        queries = PersonsQueries(sa_sync_conn)

        response = queries.person_addresses(person, page=1, per_page=50)
        summary = queries.person_address_summary(person)

        assert [address.id for address in response.addresses] == [raw_address]
        assert [y.publications_with_address for y in summary.years] == [1]

    def test_addresses_from_ranking_sources_on_publications_only(self, sa_sync_conn):
        """Les adresses d'un enregistrement HAL et celles d'un jeu de données sont absentes des adresses, du compte des publications avec adresse et des publications de l'adresse."""
        person = insert_person(sa_sync_conn, "Adressee")
        shared = insert_address(sa_sync_conn, "Institut Pascal, Aubière, France")
        kept = None
        for doc_type, source in (("article", "wos"), ("article", "hal"), ("dataset", "openalex")):
            publication = insert_publication(sa_sync_conn, doc_type=doc_type)
            insert_contribution(sa_sync_conn, publication, person_id=person, roles=["author"])
            member = insert_aligned_source_contribution(
                sa_sync_conn, publication, person, source=source
            )
            insert_source_contribution_address(sa_sync_conn, member, address_id=shared)
            if source == "wos":
                kept = publication
        queries = PersonsQueries(sa_sync_conn)

        response = queries.person_addresses(person, page=1, per_page=50)
        summary = queries.person_address_summary(person)
        items = AddressesQueries(sa_sync_conn).get_address_publications(
            shared, 20, scope=person_scope(person)
        )

        assert [(a.id, a.publication_count) for a in response.addresses] == [(shared, 1)]
        assert [y.publications_with_address for y in summary.years] == [1]
        assert [p.id for p in items] == [kept]


class TestAddressesByYear:
    """Adresses de la personne : CHU sur deux publications de 2024 et une de 2021, UCA sur une de 2024, une publication de 2024 sans adresse."""

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
            ("old", 2021, [chu_address]),
        ):
            publication = insert_publication(conn, publication_year=year)
            publications[key] = publication
            insert_contribution(conn, publication, person_id=person, roles=["author"])
            member = insert_aligned_source_contribution(conn, publication, person)
            for address in addresses:
                insert_source_contribution_address(conn, member, address_id=address)
        # Un coauteur d'une autre publication de 2024 porte aussi l'adresse du CHU.
        other_person = insert_person(conn, "Coauteur")
        other_publication = insert_publication(conn, publication_year=2024)
        insert_contribution(conn, other_publication, person_id=other_person, roles=["author"])
        other = insert_aligned_source_contribution(conn, other_publication, other_person)
        insert_source_contribution_address(conn, other, address_id=chu_address)
        return person, publications, {"chu": chu, "uca": uca}, chu_address, uca_address

    def test_addresses_sorted_by_publication_count(self, sa_sync_conn):
        person, _, _, chu_address, uca_address = self._setup(sa_sync_conn)

        response = PersonsQueries(sa_sync_conn).person_addresses(person, page=1, per_page=50)

        assert [(a.id, a.publication_count) for a in response.addresses] == [
            (chu_address, 3),
            (uca_address, 1),
        ]

    def test_summary_counts_publications_per_structure_and_year(self, sa_sync_conn):
        """Années consécutives de 2021 à 2024, à zéro sans publication avec adresse ; le lien rejeté n'est pas compté ; le CHU, présent dans les deux adresses de la publication a, compte une fois pour elle ; une publication de 2025 sans adresse est ignorée."""
        person, _, structures, _, _ = self._setup(sa_sync_conn)
        publication = insert_publication(sa_sync_conn, publication_year=2025)
        insert_contribution(sa_sync_conn, publication, person_id=person, roles=["author"])

        summary = PersonsQueries(sa_sync_conn).person_address_summary(person)

        assert [(y.year, y.publications_with_address) for y in summary.years] == [
            (2021, 1),
            (2022, 0),
            (2023, 0),
            (2024, 2),
        ]
        assert [(s.id, s.publications) for s in summary.structures] == [
            (structures["chu"], [1, 0, 0, 2]),
            (structures["uca"], [0, 0, 0, 1]),
        ]

    def test_address_publications_restricted_to_person(self, sa_sync_conn):
        person, publications, _, chu_address, _ = self._setup(sa_sync_conn)

        items = AddressesQueries(sa_sync_conn).get_address_publications(
            chu_address, 20, scope=person_scope(person)
        )

        assert {p.id for p in items} == {publications["a"], publications["b"], publications["old"]}
