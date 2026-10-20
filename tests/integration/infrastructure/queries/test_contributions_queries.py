"""Tests d'intégration pour `infrastructure.read_models.contributions`."""

from application.ports.read_models.contributions_queries import OrphanFilters
from infrastructure.read_models.contributions import PgContributionsQueries
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_record
from tests.integration.helpers.structures import add_source_contribution_structure, insert_structure


class TestOrphanContributionsCount:
    def test_counts_orphans(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_record(sa_sync_conn, pub)
        insert_signature(
            sa_sync_conn, sd, author_position=0, person_id=None, in_perimeter=True
        )  # orpheline
        pid = insert_person(sa_sync_conn)
        insert_signature(
            sa_sync_conn, sd, author_position=1, person_id=pid, in_perimeter=True
        )  # attribuée

        assert PgContributionsQueries(sa_sync_conn).orphan_contributions_count().total >= 1

    def test_excludes_out_of_perimeter(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_record(sa_sync_conn, pub)
        insert_signature(sa_sync_conn, sd, person_id=None, in_perimeter=False)
        assert PgContributionsQueries(sa_sync_conn).orphan_contributions_count().total == 0

    def test_excludes_non_author_roles(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_record(sa_sync_conn, pub, source="theses", source_id="t1")
        insert_signature(
            sa_sync_conn,
            sd,
            source="theses",
            person_id=None,
            roles=["thesis_director"],
            in_perimeter=True,
        )
        insert_signature(
            sa_sync_conn,
            sd,
            source="theses",
            author_position=1,
            person_id=None,
            roles=["jury_member"],
            in_perimeter=True,
        )
        assert PgContributionsQueries(sa_sync_conn).orphan_contributions_count().total == 0


def _list(conn, **filters):
    return PgContributionsQueries(conn).list_orphan_contributions(
        filters=OrphanFilters(**filters), page=1, per_page=50
    )


class TestListOrphanContributions:
    def test_lists_orphan_contributions(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_record(sa_sync_conn, pub)
        sa = insert_signature(
            sa_sync_conn, sd, person_id=None, raw_author_name="Dupond Jean", in_perimeter=True
        )

        res = _list(sa_sync_conn)
        assert res.total >= 1
        assert any(a.source_contribution_id == sa for a in res.contributions)

    def test_nom_et_prenom_separes_par_la_source(self, sa_sync_conn):
        sd = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        sa = insert_signature(
            sa_sync_conn,
            sd,
            raw_author_name=None,
            raw_last_name="Caldefie Chezet",
            raw_first_name="Zorphine",
            in_perimeter=True,
        )

        res = _list(sa_sync_conn, search="zorphine caldefie")
        [orphan] = [a for a in res.contributions if a.source_contribution_id == sa]
        assert (orphan.full_name, orphan.last_name, orphan.first_name) == (
            "Zorphine Caldefie Chezet",
            "Caldefie Chezet",
            "Zorphine",
        )

    def test_filters_by_search(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_record(sa_sync_conn, pub)
        sa_match = insert_signature(
            sa_sync_conn,
            sd,
            author_position=0,
            person_id=None,
            raw_author_name="SpecialName",
            in_perimeter=True,
        )
        insert_signature(
            sa_sync_conn,
            sd,
            author_position=1,
            person_id=None,
            raw_author_name="Autre",
            in_perimeter=True,
        )

        res = _list(sa_sync_conn, search="Special")
        assert sa_match in [a.source_contribution_id for a in res.contributions]

    def _labs_setup(self, conn):
        """Signature « Zzorph Avec » au labo LAB et à une équipe ; « Zzorph Autre » au labo AUTRE ; « Zzorph Sans » sans structure."""
        lab, other_lab, team = (
            insert_structure(conn, code, acronym=acronym, structure_type=stype)
            for code, acronym, stype in (
                ("ORPH-LAB", "LAB", "labo"),
                ("ORPH-OTHER", "AUTRE", "labo"),
                ("ORPH-TEAM", "EQ", "equipe"),
            )
        )
        sd = insert_source_record(conn, insert_publication(conn))
        sa = insert_signature(
            conn, sd, author_position=0, raw_author_name="Zzorph Avec", in_perimeter=True
        )
        other = insert_signature(
            conn, sd, author_position=1, raw_author_name="Zzorph Autre", in_perimeter=True
        )
        none = insert_signature(
            conn, sd, author_position=2, raw_author_name="Zzorph Sans", in_perimeter=True
        )
        add_source_contribution_structure(conn, sa, lab)
        add_source_contribution_structure(conn, sa, team)
        add_source_contribution_structure(conn, other, other_lab)
        return {"lab": lab, "other_lab": other_lab, "sa": sa, "other": other, "none": none}

    def test_filters_by_lab(self, sa_sync_conn):
        ids = self._labs_setup(sa_sync_conn)

        def listed(**filters):
            return {
                a.source_contribution_id
                for a in _list(sa_sync_conn, search="Zzorph", **filters).contributions
            }

        assert listed(lab_ids=[ids["lab"]]) == {ids["sa"]}
        assert listed(lab_none=True) == {ids["none"]}
        assert listed(lab_ids=[ids["other_lab"]], lab_none=True) == {ids["other"], ids["none"]}

    def test_lab_facet_ignores_the_lab_filter(self, sa_sync_conn):
        ids = self._labs_setup(sa_sync_conn)

        facets = PgContributionsQueries(sa_sync_conn).orphan_contributions_facets(
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

        (row,) = _list(sa_sync_conn, search="Zzorph Avec").contributions
        assert [(lab_item.id, lab_item.label) for lab_item in row.labs] == [(ids["lab"], "LAB")]
