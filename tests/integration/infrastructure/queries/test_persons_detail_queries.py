"""Tests d'intégration pour `infrastructure.read_models.persons.detail`."""

from functools import partial

from infrastructure.read_models.persons.detail import person_theses
from tests.integration.helpers.authorships import insert_authorship
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication

# Authorship du périmètre.
_in_perimeter_authorship = partial(insert_authorship, in_perimeter=True)


def _theses(conn, person_id):
    return [
        thesis for section in person_theses(conn, person_id).sections for thesis in section.theses
    ]


class TestPersonTheses:
    def test_author_name_matches_author_person_id(self, sa_sync_conn):
        """Deux doctorants sur la thèse : le nom d'auteur affiché correspond à `author_person_id`
        (une seule ligne pour les deux, plutôt que deux `LIMIT 1` qui pouvaient diverger)."""
        jury = insert_person(sa_sync_conn, "Jury", first_name="Jean")
        alice = insert_person(sa_sync_conn, "Doctorant", first_name="Alice")
        bruno = insert_person(sa_sync_conn, "Doctorant", first_name="Bruno")
        pub = insert_publication(sa_sync_conn, doc_type="thesis")
        _in_perimeter_authorship(sa_sync_conn, pub, person_id=jury, roles=["jury_member"])
        _in_perimeter_authorship(sa_sync_conn, pub, person_id=alice, roles=["author"])
        _in_perimeter_authorship(sa_sync_conn, pub, person_id=bruno, roles=["author"])

        theses = _theses(sa_sync_conn, jury)

        assert len(theses) == 1
        thesis = theses[0]
        expected = {alice: "Alice Doctorant", bruno: "Bruno Doctorant"}
        assert thesis.author_name == expected[thesis.author_person_id]

    def test_these_soutenue_ailleurs_et_ouvrage_dirige(self, sa_sync_conn):
        """Une thèse sans notice theses.fr figure parmi les thèses de son rapporteur ; un ouvrage dont la personne est éditrice n'y figure pas."""
        person = insert_person(sa_sync_conn, "Rapporteur")
        these = insert_publication(sa_sync_conn, "Thèse soutenue ailleurs", doc_type="thesis")
        ouvrage = insert_publication(sa_sync_conn, "Ouvrage dirigé", doc_type="book")
        insert_authorship(sa_sync_conn, these, person_id=person, roles=["rapporteur"])
        insert_authorship(sa_sync_conn, ouvrage, person_id=person, roles=["editor"])

        assert [thesis.title for thesis in _theses(sa_sync_conn, person)] == [
            "Thèse soutenue ailleurs"
        ]
