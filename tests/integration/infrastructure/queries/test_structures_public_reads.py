"""Tests d'intégration des lectures de structure servant la page publique des laboratoires."""

import csv
import io
from datetime import date
from functools import partial

from sqlalchemy import text

from domain.documents.dates import DatePrecision, PublicationDate
from infrastructure.read_models.addresses.queries import AddressesQueries
from infrastructure.read_models.addresses.scoped import lab_members_scope
from infrastructure.read_models.structures.models import StructureFilters
from infrastructure.read_models.structures.queries import StructuresQueries
from pipeline.transformation.structures.perimeter import refresh_perimeter_structures
from tests.integration.helpers.addresses import (
    insert_address,
    insert_address_structure,
)
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_hr_period, insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_aligned_source_contribution,
    insert_source_contribution_address,
)
from tests.integration.helpers.structures import (
    add_contribution_structure,
    insert_persons_perimeter,
    insert_structure,
    insert_tutelle,
)
from tests.integration.helpers.subjects import (
    insert_publication_subject,
    insert_subject,
    refresh_subject_usage,
)

# Contribution du périmètre, de rôle auteur.
_lab_author = partial(insert_contribution, in_perimeter=True, roles=["author"])


def _setup_perimeter(conn, lab_ids, code="uca"):
    root = insert_persons_perimeter(conn, code, extra_root_ids=lab_ids)
    # tutelle de la racine sur chaque descendant
    for lab in lab_ids:
        insert_tutelle(conn, root, child_id=lab)
    # Matérialise la clôture du périmètre : `get_perimeter_structure_ids` lit la table `perimeter_structures`, peuplée par `refresh_perimeter_structures`.
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
        assert res.has_partners is False
        assert res.has_addresses is False

    def test_members_count_counts_retained_current_members(self, sa_sync_conn):
        """Seule la personne retenue et présente compte parmi les membres."""
        lab = insert_structure(sa_sync_conn, "LAB-MEMBERS")
        present = insert_person(sa_sync_conn, "Presenty")
        insert_hr_period(sa_sync_conn, present, unit_label="LAB", structure_id=lab)
        gone = insert_person(sa_sync_conn, "Goney")
        insert_hr_period(
            sa_sync_conn, gone, unit_label="LAB", structure_id=lab, end_date=date(2020, 1, 1)
        )
        excluded = insert_person(sa_sync_conn, "Excludy")
        insert_hr_period(sa_sync_conn, excluded, unit_label="LAB", structure_id=lab)
        sa_sync_conn.execute(
            text("UPDATE persons SET exclusion = 'out_of_perimeter' WHERE id = :p"), {"p": excluded}
        )

        res = StructuresQueries(sa_sync_conn).get_structure_detail(lab)

        assert res is not None
        assert res.members_count == 1


class TestGetLaboratoryAddresses:
    """Adresses des publications des membres du laboratoire pendant leur présence. Alice, présente du 1er janvier 2020 au 30 juin 2022, signe en 2021 avec Bruno, présent depuis 2021 ; Alice signe aussi une publication de 2019 et une publication de 2022 datée à l'année ; Bruno signe en 2024 ; une non-membre porte l'adresse du laboratoire."""

    def _setup(self, conn):
        lab = insert_structure(conn, "LAB", acronym="LAB")
        uca = insert_structure(conn, "UCA", acronym="UCA")
        lab_address = insert_address(conn, "LAB, Clermont-Ferrand, France")
        uca_address = insert_address(conn, "Université Clermont Auvergne, France")
        insert_address_structure(conn, lab_address, structure_id=lab)
        insert_address_structure(conn, uca_address, structure_id=uca)
        alice = insert_person(conn, "Alice")
        bruno = insert_person(conn, "Bruno")
        outsider = insert_person(conn, "Externe")
        insert_hr_period(
            conn, alice, structure_id=lab, start_date=date(2020, 1, 1), end_date=date(2022, 6, 30)
        )
        insert_hr_period(conn, bruno, structure_id=lab, start_date=date(2021, 1, 1))
        publications = {}
        for key, publication_date, authors in (
            (
                "shared",
                PublicationDate(date(2021, 5, 1), DatePrecision.DAY),
                [(alice, lab_address), (bruno, uca_address)],
            ),
            ("before", PublicationDate.of_year(2019), [(alice, lab_address)]),
            ("departure_year", PublicationDate.of_year(2022), [(alice, lab_address)]),
            ("bruno", PublicationDate.of_year(2024), [(bruno, uca_address)]),
            ("outsider", PublicationDate.of_year(2021), [(outsider, lab_address)]),
        ):
            publication = insert_publication(conn, publication_date=publication_date)
            publications[key] = publication
            for person, address in authors:
                insert_contribution(conn, publication, person_id=person, roles=["author"])
                member = insert_aligned_source_contribution(conn, publication, person)
                insert_source_contribution_address(conn, member, address_id=address)
        return lab, uca, lab_address, uca_address, publications

    def test_summary_counts_member_publications_during_presence(self, sa_sync_conn):
        """La publication de 2021 signée par deux membres compte une fois ; celles d'avant l'arrivée, de l'année du départ datée à l'année et de la non-membre sont exclues."""
        lab, uca, _, _, _ = self._setup(sa_sync_conn)

        summary = StructuresQueries(sa_sync_conn).get_structure_address_summary(lab)

        assert [(y.year, y.publications_with_address) for y in summary.years] == [
            (2021, 1),
            (2022, 0),
            (2023, 0),
            (2024, 1),
        ]
        assert [(s.id, s.publications) for s in summary.structures] == [
            (uca, [1, 0, 0, 1]),
            (lab, [1, 0, 0, 0]),
        ]

    def test_addresses_of_member_publications(self, sa_sync_conn):
        lab, _, lab_address, uca_address, _ = self._setup(sa_sync_conn)

        res = StructuresQueries(sa_sync_conn).get_structure_addresses(lab, page=1, per_page=50)

        assert [(a.id, a.publication_count) for a in res.addresses] == [
            (uca_address, 2),
            (lab_address, 1),
        ]

    def test_profile_signals_addresses_of_members_only(self, sa_sync_conn):
        """Le laboratoire a des adresses ; l'UCA, sans membre, n'en a pas, bien que ses adresses figurent dans les publications."""
        lab, uca, _, _, _ = self._setup(sa_sync_conn)
        queries = StructuresQueries(sa_sync_conn)

        lab_detail = queries.get_structure_detail(lab)
        uca_detail = queries.get_structure_detail(uca)

        assert lab_detail is not None
        assert uca_detail is not None
        assert lab_detail.has_addresses is True
        assert uca_detail.has_addresses is False

    def test_address_publications_restricted_to_members(self, sa_sync_conn):
        lab, _, lab_address, _, publications = self._setup(sa_sync_conn)

        items = AddressesQueries(sa_sync_conn).get_address_publications(
            lab_address, 20, scope=lab_members_scope(lab)
        )

        assert [p.id for p in items] == [publications["shared"]]


class TestGetLaboratorySubjects:
    def test_top_subjects_by_frequency(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "L1")
        _setup_perimeter(sa_sync_conn, [lab])

        pid = insert_person(sa_sync_conn)

        # 3 publications du laboratoire, aux sujets variables.
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
        # AI sur 3 publications ; Biology sur 1.
        for p in (p1, p2, p3):
            insert_publication_subject(sa_sync_conn, p, subject_id=ai)
        insert_publication_subject(sa_sync_conn, p1, subject_id=bio)
        refresh_subject_usage(sa_sync_conn)

        res = StructuresQueries(sa_sync_conn).get_structure_subjects(lab, limit=10)
        assert len(res) == 2
        assert res[0].label == "AI"
        assert res[0].count == 3
        assert res[1].label == "Biology"
        assert res[1].count == 1
