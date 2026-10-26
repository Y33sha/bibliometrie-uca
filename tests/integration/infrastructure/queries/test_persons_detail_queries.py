"""Tests d'intégration pour `infrastructure.read_models.persons.detail`."""

from functools import partial

from sqlalchemy import text

from infrastructure.read_models.persons.queries import PersonsQueries
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)

# Contribution du périmètre.
_in_perimeter_contribution = partial(insert_contribution, in_perimeter=True)


def _source_contribution(conn, publication_id, *, source="hal", roles=None):
    """Contribution source sur un enregistrement source de la publication, d'identifiant source unique."""
    source_record_id = insert_source_record(
        conn, publication_id, source=source, source_id=f"detail-{publication_id}-{source}"
    )
    return insert_source_contribution(
        conn, source_record_id, source=source, roles=roles
    ), source_record_id


def _join_group(conn, source_contribution, *, publication_id, person_id):
    """Ajoute la contribution source `(id, enregistrement source)` au groupe de la personne dans la publication."""
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
        """Deux doctorants sur la thèse : le nom d'auteur affiché correspond à `author_person_id`
        (une seule ligne pour les deux, plutôt que deux `LIMIT 1` qui pouvaient diverger)."""
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
    """Les lectures d'affichage passent par les membres des groupes de la personne."""

    def test_theses_count_counts_member_non_author_theses(self, sa_sync_conn):
        person = insert_person(sa_sync_conn, "Directrice")
        thesis = insert_publication(sa_sync_conn, doc_type="thesis")
        insert_contribution(sa_sync_conn, thesis, person_id=person, roles=["thesis_director"])
        member = _source_contribution(
            sa_sync_conn, thesis, source="theses", roles=["thesis_director"]
        )
        _join_group(sa_sync_conn, member, publication_id=thesis, person_id=person)

        profile = PersonsQueries(sa_sync_conn).person_profile(person)

        assert profile is not None
        assert profile.theses_count == 1

    def test_addresses_come_from_group_members(self, sa_sync_conn):
        """L'adresse d'un membre du groupe figure ; celle d'une contribution source hors des groupes de la personne, non."""
        person = insert_person(sa_sync_conn, "Adressee")
        publication = insert_publication(sa_sync_conn)
        other_publication = insert_publication(sa_sync_conn)
        insert_contribution(sa_sync_conn, publication, person_id=person, roles=["author"])
        member = _source_contribution(sa_sync_conn, publication)
        _join_group(sa_sync_conn, member, publication_id=publication, person_id=person)
        outsider, _ = _source_contribution(sa_sync_conn, other_publication)
        member_address = insert_address(sa_sync_conn, "Membre du groupe")
        insert_source_contribution_address(sa_sync_conn, member[0], address_id=member_address)
        insert_source_contribution_address(
            sa_sync_conn, outsider, address_id=insert_address(sa_sync_conn, "Hors groupe")
        )

        response = PersonsQueries(sa_sync_conn).person_addresses(person, page=1, per_page=50)

        assert [address.id for address in response.addresses] == [member_address]
