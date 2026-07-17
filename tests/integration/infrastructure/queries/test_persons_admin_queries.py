"""Tests d'intégration pour `infrastructure.queries.api.persons.admin`."""

from sqlalchemy import text

from infrastructure.queries.api.persons.admin import (
    detachable_intruders,
    detachable_intruders_count,
    identifier_conflicts,
    identifier_conflicts_count,
    list_orphan_authorships,
    name_duplicates,
    name_duplicates_count,
    name_form_authorships,
    orphan_authorships_count,
)
from tests.integration.helpers.authorships import upsert_identity


def _create_authorship(conn, pub_id, person_id):
    conn.execute(
        text(
            "INSERT INTO authorships (publication_id, person_id, roles) "
            "VALUES (:p, :pe, ARRAY['author']::text[])"
        ),
        {"p": pub_id, "pe": person_id},
    )


def _create_person(conn, last="A", first="Z", rejected=False):
    row = conn.execute(
        text(
            "INSERT INTO persons "
            "(last_name, first_name, last_name_normalized, first_name_normalized, rejected) "
            "VALUES (:l, :f, lower(:l), lower(:f), :r) RETURNING id"
        ),
        {"l": last, "f": first, "r": rejected},
    ).one()
    return row.id


def _create_pub(conn, doc_type="article"):
    row = conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, CAST(:dt AS doc_type)) RETURNING id"
        ),
        {"dt": doc_type},
    ).one()
    return row.id


def _create_sd(conn, pub_id, source="hal", source_id="h1"):
    row = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES (:src, :sid, 'X', :pid) RETURNING id"
        ),
        {"src": source, "sid": source_id, "pid": pub_id},
    ).one()
    return row.id


def _create_sa(
    conn,
    sd,
    *,
    source="hal",
    author_position=0,
    person_id=None,
    in_perimeter=True,
    author_name_normalized=None,
    raw_author_name="X",
    roles=None,
):
    identity_id = upsert_identity(conn, author_name_normalized=author_name_normalized)
    row = conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position,
                 person_id, in_perimeter, identity_id, raw_author_name,
                 roles)
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
    ).one()
    return row.id


class TestOrphanAuthorshipsCount:
    def test_counts_orphans(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, author_position=0, person_id=None)  # orpheline
        pid = _create_person(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, author_position=1, person_id=pid)  # attribuée

        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] >= 1

    def test_excludes_non_uca(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, person_id=None, in_perimeter=False)
        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] == 0

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
        count = orphan_authorships_count(sa_sync_conn)
        assert count["total"] == 0


class TestListOrphanAuthorships:
    def test_lists_orphan_authorships(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa = _create_sa(sa_sync_conn, sd, person_id=None, raw_author_name="Dupond Jean")

        res = list_orphan_authorships(sa_sync_conn, search="", page=1, per_page=50)
        assert res["total"] >= 1
        assert any(a["authorship_id"] == sa for a in res["authorships"])

    def test_filters_by_search(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        sa_match = _create_sa(
            sa_sync_conn, sd, author_position=0, person_id=None, raw_author_name="SpecialName"
        )
        _create_sa(sa_sync_conn, sd, author_position=1, person_id=None, raw_author_name="Autre")

        res = list_orphan_authorships(sa_sync_conn, search="Special", page=1, per_page=50)
        ids = [a["authorship_id"] for a in res["authorships"]]
        assert sa_match in ids


class TestNameFormAuthorships:
    def test_returns_authorships_and_other_persons(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn, last="Dupond")
        other = _create_person(sa_sync_conn, last="Martin")
        pub = _create_pub(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, person_id=pid, author_name_normalized="dupond j")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources) "
                "VALUES ('dupond j', :pid, ARRAY['hal']), "
                "       ('dupond j', :other, ARRAY['hal'])"
            ),
            {"pid": pid, "other": other},
        )

        res = name_form_authorships(sa_sync_conn, pid, "dupond j")
        assert len(res["authorships"]) >= 1
        other_ids = [p["id"] for p in res["other_persons"]]
        assert other in other_ids


# Tests pour `hal_duplicate_accounts` déplacés vers
# `tests/integration/infrastructure/queries/test_hal_problems.py` —
# la query est maintenant exposée par PgHalProblemsQueries.


def _sa_with_identifiers(conn, sd, position, person_id, identifiers):
    """Signature portant `identifiers` : l'identité (nom normalisé absent + identifiants) est
    upsertée dans `author_identifying_keys`, la signature la référence par `identity_id`."""
    identity_id = upsert_identity(conn, person_identifiers=identifiers)
    conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, person_id,
                 raw_author_name, identity_id)
            VALUES ('hal', :sd, :pos, :pid, 'X', :iid)
        """),
        {"sd": sd, "pos": position, "pid": person_id, "iid": identity_id},
    )


class TestIdentifierConflicts:
    """La détection projette `(person_id, id_type, id_value)` à la volée depuis
    `source_authorships` ⋈ `author_identifying_keys` : rien à rafraîchir, la lecture voit
    directement le seed de la transaction rollbackée du fixture."""

    def test_pair_sharing_orcid(self, sa_sync_conn):
        p1 = _create_person(sa_sync_conn, last="Smith", first="John")
        p2 = _create_person(sa_sync_conn, last="Smith", first="J")
        sd = _create_sd(sa_sync_conn, _create_pub(sa_sync_conn))
        _sa_with_identifiers(sa_sync_conn, sd, 0, p1, {"orcid": "0000-0001-2345-6789"})
        _sa_with_identifiers(sa_sync_conn, sd, 1, p2, {"orcid": "0000-0001-2345-6789"})

        assert identifier_conflicts_count(sa_sync_conn) == 1
        res = identifier_conflicts(sa_sync_conn, page=1, per_page=50)
        assert res["total"] == 1
        pair = res["pairs"][0]
        assert {pair["person_a"]["person_id"], pair["person_b"]["person_id"]} == {p1, p2}
        assert pair["shared_identifiers"] == [
            {"id_type": "orcid", "id_value": "0000-0001-2345-6789"}
        ]

    def test_dubious_excluded(self, sa_sync_conn):
        p1 = _create_person(sa_sync_conn, last="Brown", first="Anne")
        p2 = _create_person(sa_sync_conn, last="Brown", first="A")
        sd = _create_sd(sa_sync_conn, _create_pub(sa_sync_conn))
        _sa_with_identifiers(sa_sync_conn, sd, 0, p1, {"orcid": "0000-0009-9999-9999_dubious"})
        _sa_with_identifiers(sa_sync_conn, sd, 1, p2, {"orcid": "0000-0009-9999-9999_dubious"})

        assert identifier_conflicts_count(sa_sync_conn) == 0


def _confirm_name_form(conn, person_id, name_form):
    conn.execute(
        text(
            "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
            "VALUES (:nf, :pid, ARRAY['hal'], 'confirmed')"
        ),
        {"nf": name_form, "pid": person_id},
    )


class TestDetachableIntruders:
    """Une même personne sur ≥2 signatures d'une même `source_publication` : départage ancre
    (nom compatible avec une forme confirmée) / intrus (incompatible) — cf.
    `audit_repeated_person_in_publication`."""

    def test_anchor_plus_intruder_is_detachable(self, sa_sync_conn):
        person = _create_person(sa_sync_conn, last="Ravoux", first="Corentin")
        _confirm_name_form(sa_sync_conn, person, "ravoux c")
        sd = _create_sd(sa_sync_conn, _create_pub(sa_sync_conn))
        _create_sa(
            sa_sync_conn, sd, author_position=0, person_id=person, author_name_normalized="ravoux c"
        )
        _create_sa(
            sa_sync_conn,
            sd,
            author_position=1,
            person_id=person,
            author_name_normalized="perez rafols i",
        )

        assert detachable_intruders_count(sa_sync_conn) == 1
        res = detachable_intruders(sa_sync_conn, page=1, per_page=50)
        assert res["total"] == 1
        group = res["groups"][0]
        assert group["person"]["person_id"] == person
        assert [a["raw_author_name"] for a in group["anchors"]] == ["X"]
        assert [i["name_form"] for i in group["intruders"]] == ["perez rafols i"]

    def test_all_compatible_not_detachable(self, sa_sync_conn):
        """Toutes les occurrences légitimes → doublon de signature, pas un détachement."""
        person = _create_person(sa_sync_conn, last="Martin", first="Paul")
        _confirm_name_form(sa_sync_conn, person, "martin p")
        sd = _create_sd(sa_sync_conn, _create_pub(sa_sync_conn))
        _create_sa(
            sa_sync_conn, sd, author_position=0, person_id=person, author_name_normalized="martin p"
        )
        _create_sa(
            sa_sync_conn,
            sd,
            author_position=1,
            person_id=person,
            author_name_normalized="martin paul",
        )

        assert detachable_intruders_count(sa_sync_conn) == 0

    def test_no_confirmed_anchor_not_detachable(self, sa_sync_conn):
        """Aucune forme confirmée compatible → bucket « sans ancre », pas détachable."""
        person = _create_person(sa_sync_conn, last="Durand", first="Jean")
        sd = _create_sd(sa_sync_conn, _create_pub(sa_sync_conn))
        _create_sa(
            sa_sync_conn, sd, author_position=0, person_id=person, author_name_normalized="durand j"
        )
        _create_sa(
            sa_sync_conn, sd, author_position=1, person_id=person, author_name_normalized="autre x"
        )

        assert detachable_intruders_count(sa_sync_conn) == 0


class TestNameDuplicates:
    """Paires aux noms compatibles, classées par recouvrement de réseau."""

    def _pair(self, res, a, b):
        return next(
            p
            for p in res["pairs"]
            if {p["person_a"]["person_id"], p["person_b"]["person_id"]} == {a, b}
        )

    def test_shared_coauthor_is_network_tier(self, sa_sync_conn):
        a = _create_person(sa_sync_conn, last="Dupont", first="J")
        b = _create_person(sa_sync_conn, last="Dupont", first="Jean")
        coauthor = _create_person(sa_sync_conn, last="Martin", first="Paul")
        pub1, pub2 = _create_pub(sa_sync_conn), _create_pub(sa_sync_conn)
        _create_authorship(sa_sync_conn, pub1, a)
        _create_authorship(sa_sync_conn, pub1, coauthor)
        _create_authorship(sa_sync_conn, pub2, b)
        _create_authorship(sa_sync_conn, pub2, coauthor)

        assert name_duplicates_count(sa_sync_conn) >= 1
        pair = self._pair(name_duplicates(sa_sync_conn, page=1, per_page=50), a, b)
        assert pair["overlaps"]["coauthors"] == 1

    def test_disjoint_pair_has_no_overlap(self, sa_sync_conn):
        a = _create_person(sa_sync_conn, last="Bernard", first="M")
        b = _create_person(sa_sync_conn, last="Bernard", first="Marie")

        pair = self._pair(name_duplicates(sa_sync_conn, page=1, per_page=50), a, b)
        assert pair["overlaps"] == {"coauthors": 0, "shared_pubs": 0, "labs": 0, "journals": 0}
