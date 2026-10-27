"""Tests d'intégration des lectures de structure servant la page publique des laboratoires."""

import csv
import io
from functools import partial

from sqlalchemy import text

from infrastructure.read_models.structures.models import StructureFilters
from infrastructure.read_models.structures.queries import StructuresQueries
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


def _perimeter_id(conn, code="uca"):
    return conn.execute(text("SELECT id FROM perimeters WHERE code = :c"), {"c": code}).scalar_one()


def _ids(conn, sort="acronym_asc", **filters):
    page = StructuresQueries(conn).list_structures(
        filters=StructureFilters(**filters), sort=sort, page=1, per_page=200
    )
    return [s.id for s in page.structures]


class TestListStructures:
    def test_filters_on_the_perimeter(self, sa_sync_conn):
        conn = sa_sync_conn
        lab = insert_structure(conn, "LAB-1", name="Lab 1")
        outside = insert_structure(conn, "LAB-OUT")
        _setup_perimeter(conn, [lab])
        ids = _ids(conn, perimeter_ids=[_perimeter_id(conn)])
        assert lab in ids
        assert outside not in ids

    def test_none_keeps_structures_outside_every_perimeter(self, sa_sync_conn):
        conn = sa_sync_conn
        lab = insert_structure(conn, "LAB-1")
        outside = insert_structure(conn, "LAB-OUT")
        _setup_perimeter(conn, [lab])
        ids = _ids(conn, perimeter_none=True)
        assert outside in ids
        assert lab not in ids
        assert {lab, outside} <= set(
            _ids(conn, perimeter_ids=[_perimeter_id(conn)], perimeter_none=True)
        )

    def test_includes_root_as_tutelle(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB-2")
        root = _setup_perimeter(sa_sync_conn, [lab])
        page = StructuresQueries(sa_sync_conn).list_structures(
            filters=StructureFilters(), sort="acronym_asc", page=1, per_page=200
        )
        lab_row = next(s for s in page.structures if s.id == lab)
        assert root in [t.id for t in (lab_row.tutelles or [])]

    def test_filters_on_types_and_tutelles(self, sa_sync_conn):
        conn = sa_sync_conn
        parent = insert_structure(conn, "UNIV", structure_type="universite")
        lab = insert_structure(conn, "LAB-D", structure_type="labo")
        team = insert_structure(conn, "TEAM-D", structure_type="equipe")
        other = insert_structure(conn, "LAB-E", structure_type="labo")
        insert_tutelle(conn, parent, child_id=lab)
        insert_tutelle(conn, parent, child_id=team)

        assert set(_ids(conn, types=["labo"])) >= {lab, other}
        assert team not in _ids(conn, types=["labo"])
        assert set(_ids(conn, tutelle_ids=[parent])) == {lab, team}
        assert _ids(conn, types=["labo"], tutelle_ids=[parent]) == [lab]

    def test_sorts_on_the_requested_column(self, sa_sync_conn):
        conn = sa_sync_conn
        a = insert_structure(conn, "TRI-A", name="Zeta", acronym="AC1")
        b = insert_structure(conn, "TRI-B", name="Alpha", acronym="AC2")
        assert _ids(conn, search="TRI-", sort="acronym_asc") == [a, b]
        assert _ids(conn, search="TRI-", sort="acronym_desc") == [b, a]
        assert _ids(conn, search="TRI-", sort="name_asc") == [b, a]

    def test_pages_the_list(self, sa_sync_conn):
        conn = sa_sync_conn
        for i in range(3):
            insert_structure(conn, f"PAGE-{i}", name=f"Page {i}")
        page = StructuresQueries(conn).list_structures(
            filters=StructureFilters(search="Page "), sort="name_asc", page=2, per_page=2
        )
        assert page.total == 3
        assert page.pages == 2
        assert [s.name for s in page.structures] == ["Page 2"]


class TestStructuresFacets:
    def test_each_facet_ignores_its_own_filter(self, sa_sync_conn):
        conn = sa_sync_conn
        parent = insert_structure(conn, "UNIV-F", structure_type="universite")
        lab = insert_structure(conn, "LAB-F", structure_type="labo")
        team = insert_structure(conn, "TEAM-F", structure_type="equipe")
        insert_tutelle(conn, parent, child_id=lab)
        insert_tutelle(conn, parent, child_id=team)
        _setup_perimeter(conn, [lab])

        facets = StructuresQueries(conn).structures_facets(
            filters=StructureFilters(types=["labo"], tutelle_ids=[parent])
        )
        types = {o.value: o.count for o in facets.types}
        assert types["labo"] >= 1
        assert types["equipe"] >= 1
        tutelle = next(o for o in facets.tutelles if o.value == str(parent))
        assert tutelle.count == 1
        perimeters = {o.value: o.count for o in facets.perimeters}
        assert perimeters[str(_perimeter_id(conn))] == 1
        assert perimeters["none"] == 0


class TestExportStructures:
    def test_writes_the_filtered_list(self, sa_sync_conn):
        conn = sa_sync_conn
        parent = insert_structure(conn, "UNIV-X", acronym="UX", structure_type="universite")
        lab = insert_structure(conn, "LAB-X", name="Labo X", acronym="LX")
        insert_tutelle(conn, parent, child_id=lab)
        content = "".join(
            StructuresQueries(conn).export_structures_csv(
                filters=StructureFilters(tutelle_ids=[parent]), sort="acronym_asc"
            )
        )
        rows = list(csv.reader(io.StringIO(content.removeprefix("﻿"))))
        assert rows == [
            ["Type", "Acronyme", "Nom", "Tutelles", "ROR", "Collection HAL"],
            ["labo", "LX", "Labo X", "UX", "", ""],
        ]


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
