"""Scope laboratoire de l'annuaire personnes (`/api/persons/directory` + facets).

Vérifie que `DirectoryFilters.lab_id` / `FacetFilters.lab_id` restreignent aux
personnes ayant un authorship (rôle author) rattaché au labo via
`authorship_structures` — l'alignement qui remplace l'ancien endpoint
`/api/laboratories/[id]/persons`.
"""

from sqlalchemy import text

from application.ports.api.persons_queries import DirectoryFilters, FacetFilters, ListFilters
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


class TestDirectoryLabScope:
    def test_directory_restricted_to_lab(self, sa_sync_conn):
        lab = _structure(sa_sync_conn, "LAB-DIR")
        p_in = _person(sa_sync_conn, "Inlab")
        _authorship_in_lab(sa_sync_conn, p_in, lab_id=lab)
        p_out = _person(sa_sync_conn, "Outlab")
        _authorship_in_lab(sa_sync_conn, p_out, lab_id=None)

        q = PgPersonsQueries(sa_sync_conn)
        res = q.persons_directory(
            filters=DirectoryFilters(lab_id=lab), page=1, per_page=50, sort="name_asc"
        )
        ids = {p.id for p in res.persons}
        assert p_in in ids
        assert p_out not in ids

    def test_directory_unscoped_includes_both(self, sa_sync_conn):
        lab = _structure(sa_sync_conn, "LAB-DIR2")
        p_in = _person(sa_sync_conn, "Inlab")
        _authorship_in_lab(sa_sync_conn, p_in, lab_id=lab)
        p_out = _person(sa_sync_conn, "Outlab")
        _authorship_in_lab(sa_sync_conn, p_out, lab_id=None)

        q = PgPersonsQueries(sa_sync_conn)
        res = q.persons_directory(filters=DirectoryFilters(), page=1, per_page=50, sort="name_asc")
        ids = {p.id for p in res.persons}
        assert {p_in, p_out} <= ids

    def test_facets_restricted_to_lab(self, sa_sync_conn):
        lab = _structure(sa_sync_conn, "LAB-FAC")
        p_in = _person(sa_sync_conn, "Inlab")
        _authorship_in_lab(sa_sync_conn, p_in, lab_id=lab)
        p_out = _person(sa_sync_conn, "Outlab")
        _authorship_in_lab(sa_sync_conn, p_out, lab_id=None)

        q = PgPersonsQueries(sa_sync_conn)
        scoped = q.persons_facets(filters=FacetFilters(lab_id=lab))
        unscoped = q.persons_facets(filters=FacetFilters())
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
        both = q.persons_facets(filters=FacetFilters(lab_id=lab))
        dupont = q.persons_facets(filters=FacetFilters(lab_id=lab, search="dupont"))
        assert both.rh.yes + both.rh.no == 2
        assert dupont.rh.yes + dupont.rh.no == 1

    def test_facets_exclude_rejected(self, sa_sync_conn):
        """Régression : les facettes excluent les personnes rejetées (comme l'annuaire)."""
        lab = _structure(sa_sync_conn, "LAB-REJ")
        p_ok = _person(sa_sync_conn, "Active")
        _authorship_in_lab(sa_sync_conn, p_ok, lab_id=lab)
        p_rej = _person(sa_sync_conn, "Rejected")
        _authorship_in_lab(sa_sync_conn, p_rej, lab_id=lab)
        sa_sync_conn.execute(
            text("UPDATE persons SET rejected = TRUE WHERE id = :id"), {"id": p_rej}
        )

        q = PgPersonsQueries(sa_sync_conn)
        res = q.persons_facets(filters=FacetFilters(lab_id=lab))
        assert res.rh.yes + res.rh.no == 1


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
            filters=ListFilters(has_pending_forms=True), page=1, per_page=50, sort="name_asc"
        )
        ids = {p.id for p in res.persons}
        assert p_pending in ids
        assert p_clean not in ids
        assert q.persons_facets(filters=FacetFilters()).pending_forms.yes >= 1

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
            filters=ListFilters(has_pending_identifiers=True), page=1, per_page=50, sort="name_asc"
        )
        ids = {p.id for p in res.persons}
        assert p_pending in ids
        assert p_clean not in ids
