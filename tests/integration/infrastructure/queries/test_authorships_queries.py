"""Tests d'intégration pour `infrastructure.read_models.authorships`."""

from sqlalchemy import text

from infrastructure.read_models.authorships import PgAuthorshipsQueries
from tests.integration.helpers.authorships import upsert_identity
from tests.integration.helpers.structures import add_source_authorship_structure


def _create_person(conn, last="A", first="Z"):
    return conn.execute(
        text(
            "INSERT INTO persons "
            "(last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).scalar_one()


def _create_pub(conn):
    return conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, 'article') RETURNING id"
        )
    ).scalar_one()


def _create_sd(conn, pub_id, source="hal", source_id="h1"):
    return conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES (:src, :sid, 'X', :pid) RETURNING id"
        ),
        {"src": source, "sid": source_id, "pid": pub_id},
    ).scalar_one()


def _create_sa(
    conn,
    sd,
    *,
    source="hal",
    author_position=0,
    person_id=None,
    in_perimeter=True,
    raw_author_name="X",
    roles=None,
):
    identity_id = upsert_identity(conn, author_name_normalized=None)
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position,
                 person_id, in_perimeter, identity_id, raw_author_name, roles)
            VALUES (:src, :sd, :pos, :pid, :inp, :iid, :raw,
                    COALESCE(:roles, ARRAY['author']::text[]))
            RETURNING id
        """),
        {
            "src": source,
            "sd": sd,
            "pos": author_position,
            "pid": person_id,
            "inp": in_perimeter,
            "iid": identity_id,
            "raw": raw_author_name,
            "roles": roles,
        },
    ).scalar_one()


class TestOrphanAuthorshipsCount:
    def test_counts_orphans(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, author_position=0, person_id=None)  # orpheline
        pid = _create_person(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, author_position=1, person_id=pid)  # attribuée

        assert PgAuthorshipsQueries(sa_sync_conn).orphan_authorships_count().total >= 1

    def test_excludes_out_of_perimeter(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, person_id=None, in_perimeter=False)
        assert PgAuthorshipsQueries(sa_sync_conn).orphan_authorships_count().total == 0

    def test_excludes_non_author_roles(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub, source="theses", source_id="t1")
        _create_sa(sa_sync_conn, sd, source="theses", person_id=None, roles=["thesis_director"])
        _create_sa(
            sa_sync_conn,
            sd,
            source="theses",
            author_position=1,
            person_id=None,
            roles=["jury_member"],
        )
        assert PgAuthorshipsQueries(sa_sync_conn).orphan_authorships_count().total == 0


class TestListOrphanAuthorships:
    def test_lists_orphan_authorships(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa = _create_sa(sa_sync_conn, sd, person_id=None, raw_author_name="Dupond Jean")

        res = PgAuthorshipsQueries(sa_sync_conn).list_orphan_authorships(
            search="", page=1, per_page=50
        )
        assert res.total >= 1
        assert any(a.source_authorship_id == sa for a in res.authorships)

    def test_filters_by_search(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa_match = _create_sa(
            sa_sync_conn, sd, author_position=0, person_id=None, raw_author_name="SpecialName"
        )
        _create_sa(sa_sync_conn, sd, author_position=1, person_id=None, raw_author_name="Autre")

        res = PgAuthorshipsQueries(sa_sync_conn).list_orphan_authorships(
            search="Special", page=1, per_page=50
        )
        assert sa_match in [a.source_authorship_id for a in res.authorships]

    def test_lists_labs_detected_in_the_signature(self, sa_sync_conn):
        """Seuls les laboratoires de la signature apparaissent, pas ceux des autres signatures de la publication ni les autres types de structure."""
        lab, other_lab, team = (
            sa_sync_conn.execute(
                text(
                    "INSERT INTO structures (code, name, acronym, structure_type) "
                    "VALUES (:c, :c, :a, CAST(:t AS structure_type)) RETURNING id"
                ),
                {"c": code, "a": acronym, "t": stype},
            ).scalar_one()
            for code, acronym, stype in (
                ("ORPH-LAB", "LAB", "labo"),
                ("ORPH-OTHER", "AUTRE", "labo"),
                ("ORPH-TEAM", "EQ", "equipe"),
            )
        )
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa = _create_sa(sa_sync_conn, sd, author_position=0, raw_author_name="Zzorph Avec")
        other = _create_sa(sa_sync_conn, sd, author_position=1, raw_author_name="Zzorph Autre")
        add_source_authorship_structure(sa_sync_conn, sa, lab)
        add_source_authorship_structure(sa_sync_conn, sa, team)
        add_source_authorship_structure(sa_sync_conn, other, other_lab)

        res = PgAuthorshipsQueries(sa_sync_conn).list_orphan_authorships(
            search="Zzorph Avec", page=1, per_page=50
        )
        (row,) = res.authorships
        assert [(lab_item.id, lab_item.label) for lab_item in row.labs] == [(lab, "LAB")]
