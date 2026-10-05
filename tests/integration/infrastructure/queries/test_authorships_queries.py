"""Tests d'intégration pour `infrastructure.read_models.authorships`."""

from sqlalchemy import text

from application.ports.read_models.authorships_queries import OrphanFilters
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
    raw_last_name=None,
    raw_first_name=None,
    roles=None,
):
    identity_id = upsert_identity(conn, author_name_normalized=None)
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position,
                 person_id, in_perimeter, identity_id, raw_author_name, raw_last_name,
                 raw_first_name, roles)
            VALUES (:src, :sd, :pos, :pid, :inp, :iid, :raw, :last, :first,
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
            "last": raw_last_name,
            "first": raw_first_name,
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


def _list(conn, **filters):
    return PgAuthorshipsQueries(conn).list_orphan_authorships(
        filters=OrphanFilters(**filters), page=1, per_page=50
    )


class TestListOrphanAuthorships:
    def test_lists_orphan_authorships(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa = _create_sa(sa_sync_conn, sd, person_id=None, raw_author_name="Dupond Jean")

        res = _list(sa_sync_conn)
        assert res.total >= 1
        assert any(a.source_authorship_id == sa for a in res.authorships)

    def test_nom_et_prenom_separes_par_la_source(self, sa_sync_conn):
        sd = _create_sd(sa_sync_conn, _create_pub(sa_sync_conn))
        sa = _create_sa(
            sa_sync_conn,
            sd,
            raw_author_name=None,
            raw_last_name="Caldefie Chezet",
            raw_first_name="Zorphine",
        )

        res = _list(sa_sync_conn, search="zorphine caldefie")
        [orphan] = [a for a in res.authorships if a.source_authorship_id == sa]
        assert (orphan.full_name, orphan.last_name, orphan.first_name) == (
            "Zorphine Caldefie Chezet",
            "Caldefie Chezet",
            "Zorphine",
        )

    def test_filters_by_search(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa_match = _create_sa(
            sa_sync_conn, sd, author_position=0, person_id=None, raw_author_name="SpecialName"
        )
        _create_sa(sa_sync_conn, sd, author_position=1, person_id=None, raw_author_name="Autre")

        res = _list(sa_sync_conn, search="Special")
        assert sa_match in [a.source_authorship_id for a in res.authorships]

    def _labs_setup(self, conn):
        """Signature « Zzorph Avec » au labo LAB et à une équipe ; « Zzorph Autre » au labo AUTRE ; « Zzorph Sans » sans structure."""
        lab, other_lab, team = (
            conn.execute(
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
        sd = _create_sd(conn, _create_pub(conn))
        sa = _create_sa(conn, sd, author_position=0, raw_author_name="Zzorph Avec")
        other = _create_sa(conn, sd, author_position=1, raw_author_name="Zzorph Autre")
        none = _create_sa(conn, sd, author_position=2, raw_author_name="Zzorph Sans")
        add_source_authorship_structure(conn, sa, lab)
        add_source_authorship_structure(conn, sa, team)
        add_source_authorship_structure(conn, other, other_lab)
        return {"lab": lab, "other_lab": other_lab, "sa": sa, "other": other, "none": none}

    def test_filters_by_lab(self, sa_sync_conn):
        ids = self._labs_setup(sa_sync_conn)

        def listed(**filters):
            return {
                a.source_authorship_id
                for a in _list(sa_sync_conn, search="Zzorph", **filters).authorships
            }

        assert listed(lab_ids=[ids["lab"]]) == {ids["sa"]}
        assert listed(lab_none=True) == {ids["none"]}
        assert listed(lab_ids=[ids["other_lab"]], lab_none=True) == {ids["other"], ids["none"]}

    def test_lab_facet_ignores_the_lab_filter(self, sa_sync_conn):
        ids = self._labs_setup(sa_sync_conn)

        facets = PgAuthorshipsQueries(sa_sync_conn).orphan_authorships_facets(
            filters=OrphanFilters(search="Zzorph", lab_ids=[ids["lab"]])
        )
        assert [(o.value, o.label, o.count) for o in facets.labs] == [
            (str(ids["other_lab"]), "AUTRE", 1),
            (str(ids["lab"]), "LAB", 1),
        ]
        assert facets.no_lab_count == 1

    def test_lists_labs_detected_in_the_signature(self, sa_sync_conn):
        """Seuls les laboratoires de la signature apparaissent, pas ceux des autres signatures de la publication ni les autres types de structure."""
        ids = self._labs_setup(sa_sync_conn)

        (row,) = _list(sa_sync_conn, search="Zzorph Avec").authorships
        assert [(lab_item.id, lab_item.label) for lab_item in row.labs] == [(ids["lab"], "LAB")]
