"""Tests de caractérisation pour application/authorships.py.

Documentent le comportement actuel des fonctions du service pour protéger
contre les régressions lors de refactos ultérieurs.
"""

import json

import pytest
from sqlalchemy import text

from application.authorships.core import (
    delete_orphan_authorships,
    exclude_authorship,
    propagate_uca_for_addresses,
)
from domain.errors import NotFoundError
from infrastructure.queries.perimeter import PgPerimeterQueries
from infrastructure.repositories import authorship_repository
from tests.integration.helpers.structures import add_authorship_structure


@pytest.fixture
def perimeter_queries():
    return PgPerimeterQueries()


@pytest.fixture
def repo(sa_sync_conn):
    return authorship_repository(sa_sync_conn)


# ── Helpers (SQLAlchemy text, paramstyle nommé) ───────────────────


def _create_person(conn, last="Dupont", first="Jean"):
    row = conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, "
            "                     last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).one()
    return row.id


def _create_publication(conn, title="Test Article", pub_year=2024):
    row = conn.execute(
        text("INSERT INTO publications (title, pub_year) VALUES (:t, :y) RETURNING id"),
        {"t": title, "y": pub_year},
    ).one()
    return row.id


def _create_source_publication(conn, publication_id, source="hal", source_id="hal-1", title="Test"):
    row = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES (:s, :sid, :t, :pid) RETURNING id"
        ),
        {"s": source, "sid": source_id, "t": title, "pid": publication_id},
    ).one()
    return row.id


def _create_authorship(conn, publication_id, person_id=None):
    row = conn.execute(
        text("INSERT INTO authorships (publication_id, person_id) VALUES (:p, :pid) RETURNING id"),
        {"p": publication_id, "pid": person_id},
    ).one()
    return row.id


def _create_source_authorship(
    conn,
    source_publication_id,
    *,
    source="hal",
    author_position=0,
    person_id=None,
    authorship_id=None,
    in_perimeter=False,
    structure_ids=None,
):
    row = conn.execute(
        text(
            "INSERT INTO source_authorships (source, source_publication_id, "
            "                                author_position, person_id, "
            "                                authorship_id, in_perimeter) "
            "VALUES (:s, :spid, :pos, :pid, :aid, :ip) RETURNING id"
        ),
        {
            "s": source,
            "spid": source_publication_id,
            "pos": author_position,
            "pid": person_id,
            "aid": authorship_id,
            "ip": in_perimeter,
        },
    ).one()
    for sid in structure_ids or []:
        conn.execute(
            text(
                "INSERT INTO source_authorship_structures (source_authorship_id, structure_id) "
                "VALUES (:sa, :s)"
            ),
            {"sa": row.id, "s": sid},
        )
    return row.id


def _create_structure(conn, code="UCA", name="UCA", structure_type="universite"):
    row = conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (:c, :n, CAST(:st AS structure_type)) RETURNING id"
        ),
        {"c": code, "n": name, "st": structure_type},
    ).one()
    return row.id


def _create_perimeter(conn, code, name, structure_ids):
    row = conn.execute(
        text(
            "INSERT INTO perimeters (code, name, structure_ids) VALUES (:c, :n, :sids) RETURNING id"
        ),
        {"c": code, "n": name, "sids": structure_ids},
    ).one()
    return row.id


def _set_config(conn, key, value):
    conn.execute(
        text("INSERT INTO config (key, value) VALUES (:k, CAST(:v AS jsonb))"),
        {"k": key, "v": json.dumps(value)},
    )


def _create_address(conn, raw_text="Université Clermont Auvergne"):
    row = conn.execute(
        text(
            "INSERT INTO addresses (raw_text, normalized_text) VALUES (:r, lower(:r)) RETURNING id"
        ),
        {"r": raw_text},
    ).one()
    return row.id


def _link_address_structure(conn, address_id, structure_id, is_confirmed=True):
    conn.execute(
        text(
            "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
            "VALUES (:aid, :sid, :ic)"
        ),
        {"aid": address_id, "sid": structure_id, "ic": is_confirmed},
    )


def _link_sa_address(conn, source_authorship_id, address_id):
    conn.execute(
        text(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
            "VALUES (:sa, :a)"
        ),
        {"sa": source_authorship_id, "a": address_id},
    )


# ── find_by_publication_id (hydratation Authorship) ──────────────


class TestFindByPublicationId:
    def test_returns_empty_tuple_if_no_authorship(self, sa_sync_conn, repo):
        pub_id = _create_publication(sa_sync_conn)
        assert repo.find_by_publication_id(pub_id) == ()

    def test_returns_empty_if_pub_does_not_exist(self, sa_sync_conn, repo):
        assert repo.find_by_publication_id(999999) == ()

    def test_hydrates_authorships_ordered_by_position(self, sa_sync_conn, repo):
        pub_id = _create_publication(sa_sync_conn)
        p1 = _create_person(sa_sync_conn, "Alpha", "A")
        p2 = _create_person(sa_sync_conn, "Beta", "B")
        # Insert dans l'ordre inverse pour vérifier le tri par author_position.
        sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id, author_position) "
                "VALUES (:p, :pid, 2)"
            ),
            {"p": pub_id, "pid": p2},
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id, author_position) "
                "VALUES (:p, :pid, 1)"
            ),
            {"p": pub_id, "pid": p1},
        )
        auths = repo.find_by_publication_id(pub_id)
        assert len(auths) == 2
        assert auths[0].person_id == p1
        assert auths[0].author_position == 1
        assert auths[1].person_id == p2
        assert auths[1].author_position == 2
        # Vérification du default bool.
        assert auths[0].in_perimeter is False

    def test_hydrates_full_authorship(self, sa_sync_conn, repo):
        pub_id = _create_publication(sa_sync_conn)
        person_id = _create_person(sa_sync_conn)
        s42 = _create_structure(sa_sync_conn, code="S42", name="S42")
        s43 = _create_structure(sa_sync_conn, code="S43", name="S43")
        aid = sa_sync_conn.execute(
            text("""
                INSERT INTO authorships
                    (publication_id, person_id, author_position, in_perimeter,
                     is_corresponding, roles)
                VALUES (:p, :pid, 3, TRUE, TRUE, CAST(:roles AS text[]))
                RETURNING id
            """),
            {"p": pub_id, "pid": person_id, "roles": ["author"]},
        ).scalar_one()
        for sid in (s42, s43):
            add_authorship_structure(sa_sync_conn, aid, sid)
        auths = repo.find_by_publication_id(pub_id)
        assert len(auths) == 1
        a = auths[0]
        assert a.publication_id == pub_id
        assert a.person_id == person_id
        assert a.author_position == 3
        assert a.in_perimeter is True
        assert a.is_corresponding is True
        assert a.roles == ("author",)
        assert a.structure_ids == (s42, s43)


# ── exclude_authorship ────────────────────────────────────────


class TestExcludeAuthorship:
    """exclude_authorship enregistre le rejet dans `rejected_authorships` et
    supprime la row `authorships`, sans toucher à la vérité source."""

    def test_rejects_and_deletes_row_preserving_source(self, sa_sync_conn, repo):
        person_id = _create_person(sa_sync_conn)
        pub_id = _create_publication(sa_sync_conn)
        sp_id = _create_source_publication(sa_sync_conn, pub_id)
        authorship_id = _create_authorship(sa_sync_conn, pub_id, person_id)
        sa_id = _create_source_authorship(
            sa_sync_conn, sp_id, person_id=person_id, authorship_id=authorship_id
        )

        exclude_authorship(authorship_id, repo=repo)

        # Row authorships supprimée
        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM authorships WHERE id = :id"), {"id": authorship_id}
            ).first()
            is None
        )
        # Rejet enregistré dans le sidecar
        assert (
            sa_sync_conn.execute(
                text(
                    "SELECT 1 FROM rejected_authorships "
                    "WHERE publication_id = :pub AND person_id = :pid"
                ),
                {"pub": pub_id, "pid": person_id},
            ).first()
            is not None
        )
        # Vérité source préservée (person_id non détaché)
        row = sa_sync_conn.execute(
            text("SELECT person_id FROM source_authorships WHERE id = :id"),
            {"id": sa_id},
        ).one()
        assert row.person_id == person_id

    def test_rebuild_does_not_recreate_rejected_pair(self, sa_sync_conn, repo):
        """Après rejet, l'insertion canonique re-skippe la paire (anti-join)."""
        from infrastructure.queries.authorships_build import insert_missing_authorships

        person_id = _create_person(sa_sync_conn)
        pub_id = _create_publication(sa_sync_conn)
        sp_id = _create_source_publication(sa_sync_conn, pub_id)
        authorship_id = _create_authorship(sa_sync_conn, pub_id, person_id)
        _create_source_authorship(
            sa_sync_conn, sp_id, person_id=person_id, authorship_id=authorship_id
        )

        exclude_authorship(authorship_id, repo=repo)
        # La source garde son person_id → insert_missing tenterait de recréer la paire.
        insert_missing_authorships(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM authorships WHERE publication_id = :p AND person_id = :pid"),
                {"p": pub_id, "pid": person_id},
            ).first()
            is None
        )

    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            exclude_authorship(999999, repo=repo)

    def test_does_not_touch_other_authorships(self, sa_sync_conn, repo):
        """Rejeter une authorship ne touche ni les autres paires ni leurs sources."""
        pub_id = _create_publication(sa_sync_conn)
        sp_id = _create_source_publication(sa_sync_conn, pub_id)

        p1 = _create_person(sa_sync_conn, "Dupont", "Jean")
        p2 = _create_person(sa_sync_conn, "Martin", "Sophie")
        a1 = _create_authorship(sa_sync_conn, pub_id, p1)
        a2 = _create_authorship(sa_sync_conn, pub_id, p2)
        _create_source_authorship(
            sa_sync_conn, sp_id, author_position=0, person_id=p1, authorship_id=a1
        )
        sa2 = _create_source_authorship(
            sa_sync_conn, sp_id, author_position=1, person_id=p2, authorship_id=a2
        )

        exclude_authorship(a1, repo=repo)

        # a2 toujours là
        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM authorships WHERE id = :id"), {"id": a2}
            ).first()
            is not None
        )
        # sa2 intacte
        row2 = sa_sync_conn.execute(
            text("SELECT person_id FROM source_authorships WHERE id = :id"), {"id": sa2}
        ).one()
        assert row2.person_id == p2


# ── delete_orphan_authorships ─────────────────────────────────


class TestDeleteOrphanAuthorships:
    """delete_orphan_authorships supprime les authorships vérité d'une
    personne qui ne sont attestées par aucune source_authorship active."""

    def test_deletes_authorship_without_source(self, sa_sync_conn, repo):
        person_id = _create_person(sa_sync_conn)
        pub_id = _create_publication(sa_sync_conn)
        _create_authorship(sa_sync_conn, pub_id, person_id)

        n = delete_orphan_authorships(person_id, repo=repo)

        assert n == 1
        rows = sa_sync_conn.execute(
            text("SELECT id FROM authorships WHERE person_id = :pid"), {"pid": person_id}
        ).all()
        assert rows == []

    def test_keeps_authorship_with_attesting_source(self, sa_sync_conn, repo):
        person_id = _create_person(sa_sync_conn)
        pub_id = _create_publication(sa_sync_conn)
        sp_id = _create_source_publication(sa_sync_conn, pub_id)
        authorship_id = _create_authorship(sa_sync_conn, pub_id, person_id)
        _create_source_authorship(
            sa_sync_conn, sp_id, person_id=person_id, authorship_id=authorship_id
        )

        n = delete_orphan_authorships(person_id, repo=repo)

        assert n == 0
        row = sa_sync_conn.execute(
            text("SELECT id FROM authorships WHERE id = :id"), {"id": authorship_id}
        ).first()
        assert row is not None

    def test_returns_zero_when_no_authorships(self, sa_sync_conn, repo):
        person_id = _create_person(sa_sync_conn)
        assert delete_orphan_authorships(person_id, repo=repo) == 0

    def test_scoped_to_person(self, sa_sync_conn, repo):
        """Ne touche que les authorships de la personne demandée."""
        p1 = _create_person(sa_sync_conn, "Dupont", "Jean")
        p2 = _create_person(sa_sync_conn, "Martin", "Sophie")
        pub_id = _create_publication(sa_sync_conn)
        _create_authorship(sa_sync_conn, pub_id, p1)
        pub2 = _create_publication(sa_sync_conn, title="Autre")
        _create_authorship(sa_sync_conn, pub2, p2)

        n = delete_orphan_authorships(p1, repo=repo)

        assert n == 1
        row = sa_sync_conn.execute(
            text("SELECT id FROM authorships WHERE person_id = :pid"), {"pid": p2}
        ).first()
        assert row is not None


# ── prune_orphan_authorships (build, global) ──────────────────


class TestPruneOrphanAuthorships:
    """`prune_orphan_authorships` (étape 1bis du build) supprime, toutes
    personnes confondues, les authorships canoniques que plus aucune
    source_authorship n'atteste — inverse d'`insert_missing_authorships`."""

    def test_deletes_orphan(self, sa_sync_conn):
        from infrastructure.queries.authorships_build import prune_orphan_authorships

        person_id = _create_person(sa_sync_conn)
        pub_id = _create_publication(sa_sync_conn)
        _create_authorship(sa_sync_conn, pub_id, person_id)

        n = prune_orphan_authorships(sa_sync_conn)

        assert n == 1
        assert sa_sync_conn.execute(text("SELECT id FROM authorships")).first() is None

    def test_keeps_attested_pair(self, sa_sync_conn):
        from infrastructure.queries.authorships_build import prune_orphan_authorships

        person_id = _create_person(sa_sync_conn)
        pub_id = _create_publication(sa_sync_conn)
        sp_id = _create_source_publication(sa_sync_conn, pub_id)
        authorship_id = _create_authorship(sa_sync_conn, pub_id, person_id)
        _create_source_authorship(
            sa_sync_conn, sp_id, person_id=person_id, authorship_id=authorship_id
        )

        n = prune_orphan_authorships(sa_sync_conn)

        assert n == 0
        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM authorships WHERE id = :id"), {"id": authorship_id}
            ).first()
            is not None
        )

    def test_global_scope_across_persons(self, sa_sync_conn):
        """Prune toutes les orphelines, pas seulement celles d'une personne ;
        une authorship attestée (autre personne, même pub) est préservée."""
        from infrastructure.queries.authorships_build import prune_orphan_authorships

        pub_id = _create_publication(sa_sync_conn)
        sp_id = _create_source_publication(sa_sync_conn, pub_id)
        p_attested = _create_person(sa_sync_conn, "Martin", "Sophie")
        p_orphan1 = _create_person(sa_sync_conn, "Dupont", "Jean")
        p_orphan2 = _create_person(sa_sync_conn, "Durand", "Alice")

        a_attested = _create_authorship(sa_sync_conn, pub_id, p_attested)
        _create_source_authorship(
            sa_sync_conn, sp_id, person_id=p_attested, authorship_id=a_attested
        )
        # Deux orphelines sur deux personnes distinctes (aucune source ne les atteste).
        _create_authorship(sa_sync_conn, pub_id, p_orphan1)
        pub2 = _create_publication(sa_sync_conn, title="Autre")
        _create_authorship(sa_sync_conn, pub2, p_orphan2)

        n = prune_orphan_authorships(sa_sync_conn)

        assert n == 2
        rows = sa_sync_conn.execute(text("SELECT person_id FROM authorships")).all()
        assert [r.person_id for r in rows] == [p_attested]


# ── propagate_uca_for_addresses ───────────────────────────────


class TestPropagateUcaForAddresses:
    """propagate_uca_for_addresses recalcule in_perimeter et structure_ids
    sur les source_authorships puis propage vers l'authorship vérité,
    après une modification sur address_structures."""

    def _setup_uca(self, conn):
        """Monte un périmètre UCA minimal + config perimeter_persons."""
        uca_id = _create_structure(conn, code="UCA", name="UCA")
        _create_perimeter(conn, "uca", "UCA", [uca_id])
        _set_config(conn, "perimeter_persons", "uca")
        return uca_id

    def test_noop_on_empty_address_ids(self, sa_sync_conn, repo, perimeter_queries):
        self._setup_uca(sa_sync_conn)
        propagate_uca_for_addresses(
            sa_sync_conn, [], repo=repo, perimeter_queries=perimeter_queries
        )
        # Pas d'assertion négative utile : on vérifie juste qu'aucune exception

    def test_noop_if_no_perimeter_configured(self, sa_sync_conn, repo, perimeter_queries):
        """Si aucun périmètre configuré, la fonction sort sans rien faire."""
        addr_id = _create_address(sa_sync_conn)
        # Aucun set_config perimeter_persons
        propagate_uca_for_addresses(
            sa_sync_conn, [addr_id], repo=repo, perimeter_queries=perimeter_queries
        )

    def test_sets_in_perimeter_when_address_confirmed(self, sa_sync_conn, repo, perimeter_queries):
        uca_id = self._setup_uca(sa_sync_conn)
        person_id = _create_person(sa_sync_conn)
        pub_id = _create_publication(sa_sync_conn)
        sp_id = _create_source_publication(sa_sync_conn, pub_id)
        authorship_id = _create_authorship(sa_sync_conn, pub_id, person_id)
        sa_id = _create_source_authorship(
            sa_sync_conn, sp_id, person_id=person_id, authorship_id=authorship_id
        )
        addr_id = _create_address(sa_sync_conn)
        _link_address_structure(sa_sync_conn, addr_id, uca_id, is_confirmed=True)
        _link_sa_address(sa_sync_conn, sa_id, addr_id)

        propagate_uca_for_addresses(
            sa_sync_conn, [addr_id], repo=repo, perimeter_queries=perimeter_queries
        )

        sa = sa_sync_conn.execute(
            text(
                "SELECT sa.in_perimeter, "
                "       (SELECT array_agg(structure_id ORDER BY structure_id) "
                "        FROM source_authorship_structures "
                "        WHERE source_authorship_id = sa.id) AS structure_ids "
                "FROM source_authorships sa WHERE sa.id = :id"
            ),
            {"id": sa_id},
        ).one()
        assert sa.in_perimeter is True
        assert sa.structure_ids == [uca_id]

        a = sa_sync_conn.execute(
            text(
                "SELECT a.in_perimeter, "
                "       (SELECT array_agg(structure_id ORDER BY structure_id) "
                "        FROM authorship_structures "
                "        WHERE authorship_id = a.id) AS structure_ids "
                "FROM authorships a WHERE a.id = :id"
            ),
            {"id": authorship_id},
        ).one()
        assert a.in_perimeter is True
        assert a.structure_ids == [uca_id]

    def test_unsets_in_perimeter_when_address_rejected(self, sa_sync_conn, repo, perimeter_queries):
        """Si l'adresse est rejetée (is_confirmed=False), la structure ne compte pas."""
        uca_id = self._setup_uca(sa_sync_conn)
        person_id = _create_person(sa_sync_conn)
        pub_id = _create_publication(sa_sync_conn)
        sp_id = _create_source_publication(sa_sync_conn, pub_id)
        authorship_id = _create_authorship(sa_sync_conn, pub_id, person_id)
        # source_authorship avec un flag in_perimeter déjà TRUE (état avant review)
        sa_id = _create_source_authorship(
            sa_sync_conn,
            sp_id,
            person_id=person_id,
            authorship_id=authorship_id,
            in_perimeter=True,
            structure_ids=[uca_id],
        )
        addr_id = _create_address(sa_sync_conn)
        _link_address_structure(sa_sync_conn, addr_id, uca_id, is_confirmed=False)
        _link_sa_address(sa_sync_conn, sa_id, addr_id)

        propagate_uca_for_addresses(
            sa_sync_conn, [addr_id], repo=repo, perimeter_queries=perimeter_queries
        )

        sa = sa_sync_conn.execute(
            text(
                "SELECT sa.in_perimeter, "
                "       (SELECT array_agg(structure_id ORDER BY structure_id) "
                "        FROM source_authorship_structures "
                "        WHERE source_authorship_id = sa.id) AS structure_ids "
                "FROM source_authorships sa WHERE sa.id = :id"
            ),
            {"id": sa_id},
        ).one()
        assert sa.in_perimeter is False
        assert sa.structure_ids is None
