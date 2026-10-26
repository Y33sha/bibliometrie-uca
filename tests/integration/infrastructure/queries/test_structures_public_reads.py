"""Tests d'intégration des lectures de structure servant la page publique des laboratoires."""

from functools import partial

from infrastructure.read_models.structures import StructuresQueries
from pipeline.transformation.structures.perimeter import refresh_perimeter_structures
from tests.integration.helpers.addresses import (
    ensure_country,
    insert_address,
    insert_address_structure,
)
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.structures import (
    add_contribution_structure,
    insert_persons_perimeter,
    insert_structure,
    insert_tutelle,
)
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject

# Contribution du périmètre, de rôle auteur.
_lab_author = partial(insert_contribution, in_perimeter=True, roles=["author"])


def _setup_perimeter(conn, lab_ids, code="uca"):
    root = insert_persons_perimeter(conn, code, extra_root_ids=lab_ids)
    # tutelle de la racine sur chaque descendant
    for lab in lab_ids:
        insert_tutelle(conn, root, child_id=lab)
    # Matérialise la clôture du périmètre : `get_perimeter_structure_ids` lit la table
    # `perimeter_structures`, peuplée par `refresh_perimeter_structures`.
    refresh_perimeter_structures(conn)
    return root


class TestListLaboratories:
    def test_lists_labos_in_perimeter(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB-1", name="Lab 1")
        _setup_perimeter(sa_sync_conn, [lab])
        labs = StructuresQueries(sa_sync_conn).list_structures(
            types=["labo"], search="", in_perimeter=True
        )
        ids = [lab_.id for lab_ in labs]
        assert lab in ids

    def test_includes_root_as_tutelle(self, sa_sync_conn):
        # La racine de périmètre (université) n'est plus masquée : elle figure dans les tutelles.
        lab = insert_structure(sa_sync_conn, "LAB-2")
        root = _setup_perimeter(sa_sync_conn, [lab])
        labs = StructuresQueries(sa_sync_conn).list_structures(
            types=["labo"], search="", in_perimeter=True
        )
        lab_row = next(lab_ for lab_ in labs if lab_.id == lab)
        tutelles_ids = [t.id for t in (lab_row.tutelles or [])]
        assert root in tutelles_ids

    def test_filters_on_the_types_asked_for(self, sa_sync_conn):
        """Les types viennent de l'appelant : la page publique y met ceux que sa configuration lui donne."""
        conn = sa_sync_conn
        lab = insert_structure(conn, "LAB-D", structure_type="labo")
        team = insert_structure(conn, "TEAM-D", structure_type="equipe")
        _setup_perimeter(conn, [lab, team])
        q = StructuresQueries(conn)

        ids = {r.id for r in q.list_structures(types=["labo"], search="", in_perimeter=True)}
        assert lab in ids
        assert team not in ids

        both = {
            r.id for r in q.list_structures(types=["labo", "equipe"], search="", in_perimeter=True)
        }
        assert {lab, team} <= both

    def test_without_types_keeps_every_type_of_the_perimeter(self, sa_sync_conn):
        conn = sa_sync_conn
        lab = insert_structure(conn, "LAB-N", structure_type="labo")
        team = insert_structure(conn, "TEAM-N", structure_type="equipe")
        _setup_perimeter(conn, [lab, team])
        ids = {
            r.id
            for r in StructuresQueries(conn).list_structures(types=[], search="", in_perimeter=True)
        }
        assert {lab, team} <= ids

    def test_without_perimeter_keeps_structures_outside_it(self, sa_sync_conn):
        conn = sa_sync_conn
        outside = insert_structure(conn, "LAB-OUT", structure_type="labo")
        ids = {
            r.id
            for r in StructuresQueries(conn).list_structures(
                types=["labo"], search="", in_perimeter=False
            )
        }
        assert outside in ids


class TestGetLaboratory:
    def test_returns_none_for_missing(self, sa_sync_conn):
        assert StructuresQueries(sa_sync_conn).get_structure_detail(999_999) is None

    def test_returns_full_profile(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB", name="Le labo", hal_collection="LAB-COL")
        res = StructuresQueries(sa_sync_conn).get_structure_detail(lab)
        assert res is not None
        assert res.structure.code == "LAB"
        assert res.structure.hal_collection == "LAB-COL"
        assert isinstance(res.parents, list)
        assert isinstance(res.children, list)
        assert isinstance(res.theses_count, int)


class TestGetLaboratoryAddresses:
    def test_lists_linked_addresses(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB")
        addr = insert_address(sa_sync_conn, "A")
        insert_address_structure(sa_sync_conn, addr, structure_id=lab, is_confirmed=True)

        res = StructuresQueries(sa_sync_conn).get_structure_addresses(lab, page=1, per_page=50)
        ids = [a.id for a in res.addresses]
        assert addr in ids

    def test_excludes_rejected_links(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB")
        addr = insert_address(sa_sync_conn, "R")
        insert_address_structure(sa_sync_conn, addr, structure_id=lab, is_confirmed=False)
        res = StructuresQueries(sa_sync_conn).get_structure_addresses(lab, page=1, per_page=50)
        ids = [a.id for a in res.addresses]
        assert addr not in ids


class TestGetLaboratoryDashboard:
    def test_returns_structure_even_when_empty(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB")
        res = StructuresQueries(sa_sync_conn).get_structure_dashboard(lab)
        assert res.publications_by_year == []
        assert res.oa.total == 0
        assert res.collab.total_articles == 0
        assert res.top_countries == []

    def test_aggregates_oa_and_countries(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "us", "USA")
        lab = insert_structure(sa_sync_conn, "LAB")
        pid = insert_person(sa_sync_conn)
        publication_id = insert_publication(
            sa_sync_conn, "X", oa_status="gold", countries=["fr", "us"]
        )
        aid = _lab_author(sa_sync_conn, publication_id, person_id=pid)
        add_contribution_structure(sa_sync_conn, aid, lab)

        res = StructuresQueries(sa_sync_conn).get_structure_dashboard(lab)
        assert res.oa.open_access == 1
        assert res.collab.international == 1
        assert any(c.code == "us" for c in res.top_countries)

    def test_excludes_non_applicable_country(self, sa_sync_conn):
        """`xx` (Non applicable) ne doit ni gonfler le compte international
        ni apparaître dans le top pays."""
        lab = insert_structure(sa_sync_conn, "LAB")
        pid = insert_person(sa_sync_conn)
        publication_id = insert_publication(
            sa_sync_conn, "Y", oa_status="closed", countries=["fr", "xx"]
        )
        aid = _lab_author(sa_sync_conn, publication_id, person_id=pid)
        add_contribution_structure(sa_sync_conn, aid, lab)

        res = StructuresQueries(sa_sync_conn).get_structure_dashboard(lab)
        assert res.collab.total_articles == 1
        assert res.collab.international == 0
        assert res.collab.domestic == 1
        assert not any(c.code == "xx" for c in res.top_countries)


class TestGetLaboratorySubjects:
    def test_top_subjects_by_frequency(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "L1")
        _setup_perimeter(sa_sync_conn, [lab])

        pid = insert_person(sa_sync_conn)

        # 3 publications du labo avec sujets variables.
        def _attach(publication_id):
            aid = _lab_author(sa_sync_conn, publication_id, person_id=pid)
            add_contribution_structure(sa_sync_conn, aid, lab)

        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        p3 = insert_publication(sa_sync_conn, "p3")
        for p in (p1, p2, p3):
            _attach(p)

        ai = insert_subject(sa_sync_conn, "AI")
        bio = insert_subject(sa_sync_conn, "Biology")
        # AI sur 3 publis ; Biology sur 1.
        for p in (p1, p2, p3):
            insert_publication_subject(sa_sync_conn, p, subject_id=ai)
        insert_publication_subject(sa_sync_conn, p1, subject_id=bio)

        res = StructuresQueries(sa_sync_conn).get_structure_subjects(lab, limit=10)
        assert len(res) == 2
        assert res[0].label == "AI"
        assert res[0].count == 3
        assert res[1].label == "Biology"
        assert res[1].count == 1
