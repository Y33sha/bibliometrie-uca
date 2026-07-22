"""Scope laboratoire de la liste des personnes (`/api/persons` + facettes).

Vérifie que `PersonFilters.lab_id` restreint aux personnes ayant une signature de rôle auteur rattachée au laboratoire via `authorship_structures`, et que le filtre `rejected` porte de la même façon sur la liste et sur ses facettes.
"""

from sqlalchemy import text

from application.ports.api.persons_queries import PersonFilters
from infrastructure.queries.api.persons import PgPersonsQueries
from tests.integration.helpers.structures import add_authorship_structure


def _structure(conn, code):
    return conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (:c, :c, 'labo') RETURNING id"
        ),
        {"c": code},
    ).scalar_one()


def _person(conn, last):
    return conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, 'Z', lower(:l), 'z') RETURNING id"
        ),
        {"l": last},
    ).scalar_one()


def _authorship_in_lab(conn, person_id, lab_id=None):
    pub = conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', 2024, 'article') RETURNING id"
        )
    ).scalar_one()
    aid = conn.execute(
        text(
            "INSERT INTO authorships (publication_id, person_id, roles) "
            "VALUES (:p, :pe, ARRAY['author']::text[]) RETURNING id"
        ),
        {"p": pub, "pe": person_id},
    ).scalar_one()
    if lab_id is not None:
        add_authorship_structure(conn, aid, lab_id)


class TestListLabScope:
    def test_list_restricted_to_lab(self, sa_sync_conn):
        lab = _structure(sa_sync_conn, "LAB-DIR")
        p_in = _person(sa_sync_conn, "Inlab")
        _authorship_in_lab(sa_sync_conn, p_in, lab_id=lab)
        p_out = _person(sa_sync_conn, "Outlab")
        _authorship_in_lab(sa_sync_conn, p_out, lab_id=None)

        q = PgPersonsQueries(sa_sync_conn)
        res = q.list_persons(
            filters=PersonFilters(lab_id=lab), page=1, per_page=50, sort="name_asc"
        )
        ids = {p.id for p in res.persons}
        assert p_in in ids
        assert p_out not in ids

    def test_list_unscoped_includes_both(self, sa_sync_conn):
        lab = _structure(sa_sync_conn, "LAB-DIR2")
        p_in = _person(sa_sync_conn, "Inlab")
        _authorship_in_lab(sa_sync_conn, p_in, lab_id=lab)
        p_out = _person(sa_sync_conn, "Outlab")
        _authorship_in_lab(sa_sync_conn, p_out, lab_id=None)

        q = PgPersonsQueries(sa_sync_conn)
        res = q.list_persons(filters=PersonFilters(), page=1, per_page=50, sort="name_asc")
        ids = {p.id for p in res.persons}
        assert {p_in, p_out} <= ids

    def test_signature_counts_scoped_to_lab(self, sa_sync_conn):
        """Sous scope labo, les dénombrements ne comptent que les signatures du labo."""
        lab = _structure(sa_sync_conn, "LAB-CNT")
        person = _person(sa_sync_conn, "Counted")
        _authorship_in_lab(sa_sync_conn, person, lab_id=lab)
        _authorship_in_lab(sa_sync_conn, person, lab_id=None)

        q = PgPersonsQueries(sa_sync_conn)
        scoped = q.list_persons(
            filters=PersonFilters(lab_id=lab), page=1, per_page=50, sort="name_asc"
        )
        unscoped = q.list_persons(
            filters=PersonFilters(search="counted"), page=1, per_page=50, sort="name_asc"
        )
        assert next(p for p in scoped.persons if p.id == person).signature_count == 1
        assert next(p for p in unscoped.persons if p.id == person).signature_count == 2

    def test_facets_restricted_to_lab(self, sa_sync_conn):
        lab = _structure(sa_sync_conn, "LAB-FAC")
        p_in = _person(sa_sync_conn, "Inlab")
        _authorship_in_lab(sa_sync_conn, p_in, lab_id=lab)
        p_out = _person(sa_sync_conn, "Outlab")
        _authorship_in_lab(sa_sync_conn, p_out, lab_id=None)

        q = PgPersonsQueries(sa_sync_conn)
        scoped = q.persons_facets(filters=PersonFilters(lab_id=lab))
        unscoped = q.persons_facets(filters=PersonFilters())
        # Le scope labo ne compte que la personne du labo (rh.no ≥ 1 scopé,
        # et strictement inférieur au global qui inclut les deux).
        assert scoped.rh.yes + scoped.rh.no == 1
        assert unscoped.rh.yes + unscoped.rh.no >= 2

    def test_facets_respect_search(self, sa_sync_conn):
        """Régression : les comptes de facettes suivent la recherche par nom."""
        lab = _structure(sa_sync_conn, "LAB-SRCH")
        p1 = _person(sa_sync_conn, "Dupont")
        _authorship_in_lab(sa_sync_conn, p1, lab_id=lab)
        p2 = _person(sa_sync_conn, "Martin")
        _authorship_in_lab(sa_sync_conn, p2, lab_id=lab)

        q = PgPersonsQueries(sa_sync_conn)
        both = q.persons_facets(filters=PersonFilters(lab_id=lab))
        dupont = q.persons_facets(filters=PersonFilters(lab_id=lab, search="dupont"))
        assert both.rh.yes + both.rh.no == 2
        assert dupont.rh.yes + dupont.rh.no == 1


class TestRejectedFilter:
    """`rejected` porte de la même façon sur la liste et sur ses facettes."""

    def test_list_and_facets_follow_rejected(self, sa_sync_conn):
        lab = _structure(sa_sync_conn, "LAB-REJ")
        p_ok = _person(sa_sync_conn, "Active")
        _authorship_in_lab(sa_sync_conn, p_ok, lab_id=lab)
        p_rej = _person(sa_sync_conn, "Rejected")
        _authorship_in_lab(sa_sync_conn, p_rej, lab_id=lab)
        sa_sync_conn.execute(
            text("UPDATE persons SET rejected = TRUE WHERE id = :id"), {"id": p_rej}
        )

        q = PgPersonsQueries(sa_sync_conn)
        kept = q.list_persons(
            filters=PersonFilters(lab_id=lab, rejected=False), page=1, per_page=50, sort="name_asc"
        )
        assert {p.id for p in kept.persons} == {p_ok}
        assert q.persons_facets(filters=PersonFilters(lab_id=lab, rejected=False)).rh.no == 1

    def test_unfiltered_keeps_both(self, sa_sync_conn):
        lab = _structure(sa_sync_conn, "LAB-REJ2")
        p_ok = _person(sa_sync_conn, "Active")
        _authorship_in_lab(sa_sync_conn, p_ok, lab_id=lab)
        p_rej = _person(sa_sync_conn, "Rejected")
        _authorship_in_lab(sa_sync_conn, p_rej, lab_id=lab)
        sa_sync_conn.execute(
            text("UPDATE persons SET rejected = TRUE WHERE id = :id"), {"id": p_rej}
        )

        q = PgPersonsQueries(sa_sync_conn)
        res = q.list_persons(
            filters=PersonFilters(lab_id=lab), page=1, per_page=50, sort="name_asc"
        )
        assert {p.id for p in res.persons} == {p_ok, p_rej}
        assert q.persons_facets(filters=PersonFilters(lab_id=lab)).rh.no == 2


class TestPendingFacets:
    """Facette « À confirmer » : formes de nom / identifiants au statut `pending`."""

    def test_pending_name_forms_filter(self, sa_sync_conn):
        p_pending = _person(sa_sync_conn, "Pendingform")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
                "VALUES ('pf', :pid, ARRAY['hal'], 'pending')"
            ),
            {"pid": p_pending},
        )
        p_clean = _person(sa_sync_conn, "Cleanform")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
                "VALUES ('cf', :pid, ARRAY['hal'], 'confirmed')"
            ),
            {"pid": p_clean},
        )

        q = PgPersonsQueries(sa_sync_conn)
        res = q.list_persons(
            filters=PersonFilters(has_pending_forms=True), page=1, per_page=50, sort="name_asc"
        )
        ids = {p.id for p in res.persons}
        assert p_pending in ids
        assert p_clean not in ids
        assert q.persons_facets(filters=PersonFilters()).pending_forms.yes >= 1

    def test_pending_identifiers_filter(self, sa_sync_conn):
        p_pending = _person(sa_sync_conn, "Pendingid")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:pid, 'orcid', '0000-0000-0000-0001', 'auto', 'pending')"
            ),
            {"pid": p_pending},
        )
        p_clean = _person(sa_sync_conn, "Cleanid")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:pid, 'orcid', '0000-0000-0000-0002', 'auto', 'confirmed')"
            ),
            {"pid": p_clean},
        )

        q = PgPersonsQueries(sa_sync_conn)
        res = q.list_persons(
            filters=PersonFilters(has_pending_identifiers=True),
            page=1,
            per_page=50,
            sort="name_asc",
        )
        ids = {p.id for p in res.persons}
        assert p_pending in ids
        assert p_clean not in ids
