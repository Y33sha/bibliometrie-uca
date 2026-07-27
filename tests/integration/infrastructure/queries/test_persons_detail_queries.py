"""Tests d'intégration pour `infrastructure.read_models.persons.detail`."""

from sqlalchemy import text

from infrastructure.read_models.persons.detail import person_theses
from tests.integration.helpers.authorships import upsert_identity


def _person(conn, last, first):
    return conn.execute(
        text(
            "INSERT INTO persons "
            "(last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).scalar_one()


def _pub(conn):
    return conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('These', 'these', 2024, CAST('article' AS doc_type)) RETURNING id"
        )
    ).scalar_one()


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
    source_pub = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title) "
            "VALUES ('theses', :sid, 'These') RETURNING id"
        ),
        {"sid": f"theses-{authorship_id}"},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO source_authorships "
            "(source, source_publication_id, authorship_id, identity_id, raw_author_name) "
            "VALUES ('theses', :sp, :aid, :iid, 'X')"
        ),
        {"sp": source_pub, "aid": authorship_id, "iid": upsert_identity(conn)},
    )


class TestPersonTheses:
    def test_author_name_matches_author_person_id(self, sa_sync_conn):
        """Deux doctorants sur la thèse : le nom d'auteur affiché correspond à `author_person_id`
        (une seule ligne pour les deux, plutôt que deux `LIMIT 1` qui pouvaient diverger)."""
        jury = _person(sa_sync_conn, "Jury", "Jean")
        alice = _person(sa_sync_conn, "Doctorant", "Alice")
        bruno = _person(sa_sync_conn, "Doctorant", "Bruno")
        pub = _pub(sa_sync_conn)
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
