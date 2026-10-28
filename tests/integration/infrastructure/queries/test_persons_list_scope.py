"""Scope laboratoire de la liste des personnes (`/api/persons` + facettes).

Vérifie que `PersonFilters.lab_id` restreint aux personnes ayant une contribution de rôle auteur rattachée au laboratoire via `contribution_structures`, et le filtre d'exclusion.
"""

from sqlalchemy import text

from domain.persons.person import PersonExclusion
from infrastructure.read_models.persons.models import PersonFilters
from infrastructure.read_models.persons.queries import PersonsQueries
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import (
    insert_person,
    insert_person_identifier,
    insert_person_name_form,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.structures import add_contribution_structure, insert_structure


def _contribution_in_lab(conn, person_id, lab_id=None, roles=("author",), in_perimeter=False):
    aid = insert_contribution(
        conn,
        insert_publication(conn),
        person_id=person_id,
        in_perimeter=in_perimeter,
        roles=list(roles),
    )
    if lab_id is not None:
        add_contribution_structure(conn, aid, lab_id)


class TestListLabScope:
    def test_list_restricted_to_lab(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB-DIR")
        p_in = insert_person(sa_sync_conn, "Inlab")
        _contribution_in_lab(sa_sync_conn, p_in, lab_id=lab)
        p_out = insert_person(sa_sync_conn, "Outlab")
        _contribution_in_lab(sa_sync_conn, p_out, lab_id=None)

        q = PersonsQueries(sa_sync_conn)
        res = q.list_persons(
            filters=PersonFilters(lab_id=lab), page=1, per_page=50, sort="name_asc"
        )
        ids = {p.id for p in res.persons}
        assert p_in in ids
        assert p_out not in ids

    def test_list_unscoped_includes_both(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB-DIR2")
        p_in = insert_person(sa_sync_conn, "Inlab")
        _contribution_in_lab(sa_sync_conn, p_in, lab_id=lab)
        p_out = insert_person(sa_sync_conn, "Outlab")
        _contribution_in_lab(sa_sync_conn, p_out, lab_id=None)

        q = PersonsQueries(sa_sync_conn)
        res = q.list_persons(filters=PersonFilters(), page=1, per_page=50, sort="name_asc")
        ids = {p.id for p in res.persons}
        assert {p_in, p_out} <= ids

    def test_contribution_counts_scoped_to_lab(self, sa_sync_conn):
        """Sous scope labo, les dénombrements comptent seulement les contributions du labo."""
        lab = insert_structure(sa_sync_conn, "LAB-CNT")
        person = insert_person(sa_sync_conn, "Counted")
        _contribution_in_lab(sa_sync_conn, person, lab_id=lab)
        _contribution_in_lab(sa_sync_conn, person, lab_id=None)

        q = PersonsQueries(sa_sync_conn)
        scoped = q.list_persons(
            filters=PersonFilters(lab_id=lab), page=1, per_page=50, sort="name_asc"
        )
        unscoped = q.list_persons(
            filters=PersonFilters(search="counted"), page=1, per_page=50, sort="name_asc"
        )
        assert next(p for p in scoped.persons if p.id == person).contribution_count == 1
        assert next(p for p in unscoped.persons if p.id == person).contribution_count == 2

    def test_contribution_counts_author_role_only(self, sa_sync_conn):
        """Les dénombrements comptent seulement les contributions en tant qu'auteur, dans la liste comme dans la fiche d'édition."""
        person = insert_person(sa_sync_conn, "Juror")
        _contribution_in_lab(sa_sync_conn, person, in_perimeter=True)
        _contribution_in_lab(sa_sync_conn, person, roles=("jury",), in_perimeter=True)

        q = PersonsQueries(sa_sync_conn)
        listed = next(
            p
            for p in q.list_persons(
                filters=PersonFilters(search="juror"), page=1, per_page=50, sort="name_asc"
            ).persons
            if p.id == person
        )
        curated = q.person_curation(person)
        assert curated is not None
        for p in (listed, curated):
            assert p.contribution_count == 1
            assert p.in_perimeter_contribution_count == 1

    def test_facets_restricted_to_lab(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB-FAC")
        p_in = insert_person(sa_sync_conn, "Inlab")
        _contribution_in_lab(sa_sync_conn, p_in, lab_id=lab)
        p_out = insert_person(sa_sync_conn, "Outlab")
        _contribution_in_lab(sa_sync_conn, p_out, lab_id=None)

        q = PersonsQueries(sa_sync_conn)
        scoped = q.persons_facets(filters=PersonFilters(lab_id=lab))
        unscoped = q.persons_facets(filters=PersonFilters())
        # Le scope labo ne compte que la personne du labo (rh.no ≥ 1 scopé,
        # et strictement inférieur au global qui inclut les deux).
        assert scoped.rh.yes + scoped.rh.no == 1
        assert unscoped.rh.yes + unscoped.rh.no >= 2

    def test_facets_respect_search(self, sa_sync_conn):
        """Régression : les comptes de facettes suivent la recherche par nom."""
        lab = insert_structure(sa_sync_conn, "LAB-SRCH")
        p1 = insert_person(sa_sync_conn, "Dupont")
        _contribution_in_lab(sa_sync_conn, p1, lab_id=lab)
        p2 = insert_person(sa_sync_conn, "Martin")
        _contribution_in_lab(sa_sync_conn, p2, lab_id=lab)

        q = PersonsQueries(sa_sync_conn)
        both = q.persons_facets(filters=PersonFilters(lab_id=lab))
        dupont = q.persons_facets(filters=PersonFilters(lab_id=lab, search="dupont"))
        assert both.rh.yes + both.rh.no == 2
        assert dupont.rh.yes + dupont.rh.no == 1


class TestExclusionFilter:
    """Le filtre d'exclusion porte de la même façon sur la liste et sur ses facettes. Les personnes sont isolées par une recherche sur leur nom."""

    SEARCH = "zzexcl"

    def _persons(self, conn):
        ids = {}
        for name, reason in (
            ("Retenue", None),
            ("Fausse", "not_a_person"),
            ("Externe", "out_of_perimeter"),
        ):
            ids[name] = insert_person(conn, f"{self.SEARCH}{name}")
            conn.execute(
                text("UPDATE persons SET exclusion = CAST(:r AS person_exclusion) WHERE id = :id"),
                {"r": reason, "id": ids[name]},
            )
        return ids

    def _listed(self, conn, *exclusions):
        page = PersonsQueries(conn).list_persons(
            filters=PersonFilters(search=self.SEARCH, exclusions=list(exclusions)),
            page=1,
            per_page=50,
            sort="name_asc",
        )
        return {p.id for p in page.persons}

    def test_filters_by_exclusion_reason(self, sa_sync_conn):
        ids = self._persons(sa_sync_conn)
        nap, oop = PersonExclusion.NOT_A_PERSON, PersonExclusion.OUT_OF_PERIMETER
        assert self._listed(sa_sync_conn) == set(ids.values())
        assert self._listed(sa_sync_conn, None) == {ids["Retenue"]}
        assert self._listed(sa_sync_conn, nap, oop) == {ids["Fausse"], ids["Externe"]}
        assert self._listed(sa_sync_conn, oop) == {ids["Externe"]}
        assert self._listed(sa_sync_conn, None, oop) == {ids["Retenue"], ids["Externe"]}

    def test_facets_follow_exclusion(self, sa_sync_conn):
        self._persons(sa_sync_conn)
        q = PersonsQueries(sa_sync_conn)
        assert q.persons_facets(filters=PersonFilters(search=self.SEARCH)).rh.no == 3
        retained = PersonFilters(search=self.SEARCH, exclusions=[None])
        assert q.persons_facets(filters=retained).rh.no == 1

    def test_excluded_person_leaves_the_lab(self, sa_sync_conn):
        """Une personne exclue n'appartient à aucun laboratoire, dès que les matviews de structures sont rafraîchies."""
        lab = insert_structure(sa_sync_conn, "LAB-EXCL")
        p_ok = insert_person(sa_sync_conn, "Active")
        _contribution_in_lab(sa_sync_conn, p_ok, lab_id=lab)
        p_excl = insert_person(sa_sync_conn, "Exclue")
        sa_sync_conn.execute(
            text("UPDATE persons SET exclusion = 'out_of_perimeter' WHERE id = :id"),
            {"id": p_excl},
        )
        _contribution_in_lab(sa_sync_conn, p_excl, lab_id=lab)

        res = PersonsQueries(sa_sync_conn).list_persons(
            filters=PersonFilters(lab_id=lab), page=1, per_page=50, sort="name_asc"
        )
        assert {p.id for p in res.persons} == {p_ok}


class TestPendingFacets:
    """Facette « À confirmer » : formes de nom / identifiants au statut `pending`."""

    def test_pending_name_forms_filter(self, sa_sync_conn):
        p_pending = insert_person(sa_sync_conn, "Pendingform")
        insert_person_name_form(
            sa_sync_conn, p_pending, name_form="pf", sources=["hal"], status="pending"
        )
        p_clean = insert_person(sa_sync_conn, "Cleanform")
        insert_person_name_form(
            sa_sync_conn, p_clean, name_form="cf", sources=["hal"], status="confirmed"
        )

        q = PersonsQueries(sa_sync_conn)
        res = q.list_persons(
            filters=PersonFilters(has_pending_forms=True), page=1, per_page=50, sort="name_asc"
        )
        ids = {p.id for p in res.persons}
        assert p_pending in ids
        assert p_clean not in ids
        assert q.persons_facets(filters=PersonFilters()).pending_forms.yes >= 1

    def test_form_derived_from_the_name_is_not_to_confirm(self, sa_sync_conn):
        """Régression : une forme dérivée du nom de la personne, confirmée d'office, comptait comme à confirmer."""
        p_canonical = insert_person(sa_sync_conn, "Canonicalform")
        insert_person_name_form(
            sa_sync_conn,
            p_canonical,
            name_form="canonicalform",
            sources=["persons", "hal"],
            status="pending",
        )

        res = PersonsQueries(sa_sync_conn).list_persons(
            filters=PersonFilters(has_pending_forms=True), page=1, per_page=50, sort="name_asc"
        )
        assert p_canonical not in {p.id for p in res.persons}

    def test_pending_identifiers_filter(self, sa_sync_conn):
        p_pending = insert_person(sa_sync_conn, "Pendingid")
        insert_person_identifier(
            sa_sync_conn,
            p_pending,
            id_type="orcid",
            id_value="0000-0000-0000-0001",
            status="pending",
        )
        p_clean = insert_person(sa_sync_conn, "Cleanid")
        insert_person_identifier(
            sa_sync_conn,
            p_clean,
            id_type="orcid",
            id_value="0000-0000-0000-0002",
            status="confirmed",
        )

        q = PersonsQueries(sa_sync_conn)
        res = q.list_persons(
            filters=PersonFilters(has_pending_identifiers=True),
            page=1,
            per_page=50,
            sort="name_asc",
        )
        ids = {p.id for p in res.persons}
        assert p_pending in ids
        assert p_clean not in ids
