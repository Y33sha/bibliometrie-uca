"""Tests d'intégration pour `infrastructure.read_models.persons.detail`."""

from sqlalchemy import text

from infrastructure.read_models.persons.detail import person_theses
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication


def _authorship(conn, pub_id, person_id, roles):
    return conn.execute(
        text(
            "INSERT INTO authorships (publication_id, person_id, roles, in_perimeter) "
            "VALUES (:p, :pe, CAST(:r AS text[]), TRUE) RETURNING id"
        ),
        {"p": pub_id, "pe": person_id, "r": roles},
    ).scalar_one()


def _link_theses_source(conn, authorship_id):
    """source_authorship `source = 'theses'` liée à l'authorship, pour l'EXISTS de `person_theses`."""
    source_pub = insert_source_publication(
        conn, source="theses", source_id=f"theses-{authorship_id}", title="These"
    )
    insert_signature(
        conn, source_pub, source="theses", author_position=None, authorship_id=authorship_id
    )


class TestPersonTheses:
    def test_author_name_matches_author_person_id(self, sa_sync_conn):
        """Deux doctorants sur la thèse : le nom d'auteur affiché correspond à `author_person_id`
        (une seule ligne pour les deux, plutôt que deux `LIMIT 1` qui pouvaient diverger)."""
        jury = insert_person(sa_sync_conn, "Jury", first_name="Jean")
        alice = insert_person(sa_sync_conn, "Doctorant", first_name="Alice")
        bruno = insert_person(sa_sync_conn, "Doctorant", first_name="Bruno")
        pub = insert_publication(sa_sync_conn)
        jury_auth = _authorship(sa_sync_conn, pub, jury, ["jury_member"])
        _authorship(sa_sync_conn, pub, alice, ["author"])
        _authorship(sa_sync_conn, pub, bruno, ["author"])
        _link_theses_source(sa_sync_conn, jury_auth)

        res = person_theses(sa_sync_conn, jury)
        theses = [thesis for section in res.sections for thesis in section.theses]
        assert len(theses) == 1
        thesis = theses[0]
        expected = {alice: "Alice Doctorant", bruno: "Bruno Doctorant"}
        assert thesis.author_name == expected[thesis.author_person_id]
