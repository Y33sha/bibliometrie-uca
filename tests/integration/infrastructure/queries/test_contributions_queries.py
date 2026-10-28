"""Tests d'intégration pour `infrastructure.read_models.contributions.queries`.

Une contribution orpheline est une contribution du périmètre, sous un rôle d'auteur, sans personne. Les tests alignent les contributions sources hors contribution et recomposent les attributs des contributions comme le pipeline (`_contribution`)."""

from sqlalchemy import text

from infrastructure.read_models.contributions.models import OrphanFilters
from infrastructure.read_models.contributions.queries import ContributionsQueries
from tests.integration.helpers.alignment import (
    align_unaligned,
    contribution_of,
    recompose_contribution_attributes,
    set_perimeter_author_contribution,
)
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import (
    add_source_contribution_ror,
    add_source_contribution_structure,
    insert_structure,
)


def _contribution(conn) -> None:
    """Contribution les contributions sources sans contribution et recompose les attributs des contributions."""
    align_unaligned(conn)
    recompose_contribution_attributes(conn)


class TestOrphanContributionsCount:
    def test_counts_orphans(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(sa_sync_conn, publication)
        insert_source_contribution(
            sa_sync_conn, source_record, author_position=0, in_perimeter=True
        )
        _contribution(sa_sync_conn)

        assert ContributionsQueries(sa_sync_conn).orphan_contributions_count().total >= 1

    def test_excludes_out_of_perimeter(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(sa_sync_conn, publication)
        insert_source_contribution(sa_sync_conn, source_record, in_perimeter=False)
        _contribution(sa_sync_conn)
        assert ContributionsQueries(sa_sync_conn).orphan_contributions_count().total == 0

    def test_excludes_contributions_with_person(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(sa_sync_conn, publication)
        source_contribution = insert_source_contribution(
            sa_sync_conn, source_record, in_perimeter=True
        )
        _contribution(sa_sync_conn)
        set_perimeter_author_contribution(
            sa_sync_conn,
            contribution_of(sa_sync_conn, source_contribution),
            person_id=insert_person(sa_sync_conn),
            mode="name",
        )
        assert ContributionsQueries(sa_sync_conn).orphan_contributions_count().total == 0

    def test_excludes_unaligned_source_contributions(self, sa_sync_conn):
        """Une contribution source hors contribution (enregistrement source écarté de l'alignement, doublon d'auteur) reste sans personne : elle n'est pas à rattacher."""
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        insert_source_contribution(sa_sync_conn, source_record, in_perimeter=True)
        assert ContributionsQueries(sa_sync_conn).orphan_contributions_count().total == 0

    def test_excludes_non_author_roles(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication, source="theses", source_id="t1"
        )
        insert_source_contribution(
            sa_sync_conn,
            source_record,
            source="theses",
            roles=["thesis_director"],
            in_perimeter=True,
        )
        insert_source_contribution(
            sa_sync_conn,
            source_record,
            source="theses",
            author_position=1,
            roles=["jury_member"],
            in_perimeter=True,
        )
        _contribution(sa_sync_conn)
        assert ContributionsQueries(sa_sync_conn).orphan_contributions_count().total == 0


def _list(conn, **filters):
    """File des orphelines, après avoir groupé les contributions sources sans contribution."""
    _contribution(conn)
    return ContributionsQueries(conn).list_orphan_contributions(
        filters=OrphanFilters(**filters), page=1, per_page=50
    )


def _hal_and_openalex_contribution(conn, hal_name: str, openalex_name: str) -> int:
    """Contribution orpheline à deux contributions sources, HAL (source prioritaire, nom affiché) et OpenAlex. Retourne son id."""
    publication = insert_publication(conn)
    hal = insert_source_contribution(
        conn, insert_source_record(conn, publication), raw_author_name=hal_name, in_perimeter=True
    )
    openalex_record = insert_source_record(
        conn, publication, source="openalex", source_id=f"W-{openalex_name}"
    )
    openalex = insert_source_contribution(
        conn, openalex_record, source="openalex", raw_author_name=openalex_name
    )
    _contribution(conn)
    contribution = contribution_of(conn, hal)
    conn.execute(
        text(
            "UPDATE aligned_source_contributions SET contribution_id = :g"
            " WHERE source_contribution_id = :s"
        ),
        {"g": contribution, "s": openalex},
    )
    recompose_contribution_attributes(conn)
    return contribution


class TestListOrphanContributions:
    def test_lists_orphan_contributions(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(sa_sync_conn, publication)
        sa = insert_source_contribution(
            sa_sync_conn,
            source_record,
            raw_author_name="Dupond Jean",
            in_perimeter=True,
        )

        res = _list(sa_sync_conn)
        assert res.total >= 1
        [orphan] = [
            a for a in res.contributions if a.contribution_id == contribution_of(sa_sync_conn, sa)
        ]
        assert (orphan.publication_id, orphan.sources) == (publication, ["hal"])

    def test_aggregates_the_source_contributions_of_the_contribution(self, sa_sync_conn):
        """Une contribution à deux contributions sources : une ligne, les sources par ordre de priorité, le nom de la contribution source de la source prioritaire."""
        contribution = _hal_and_openalex_contribution(
            sa_sync_conn, "Zzmembre Hal", "Zzmembre Openalex"
        )

        (orphan,) = _list(sa_sync_conn, search="Zzmembre").contributions
        assert orphan.contribution_id == contribution
        assert orphan.sources == ["hal", "openalex"]
        assert orphan.full_name == "Zzmembre Hal"

    def test_search_matches_the_displayed_name_only(self, sa_sync_conn):
        """Le nom de la contribution source OpenAlex, absent de l'affichage, ne retient pas la contribution."""
        _hal_and_openalex_contribution(sa_sync_conn, "Zzaffiche Hal", "Zzcache Openalex")
        facets = ContributionsQueries(sa_sync_conn).orphan_contributions_facets(
            filters=OrphanFilters(search="Zzcache")
        )

        assert _list(sa_sync_conn, search="Zzcache").total == 0
        assert facets.no_lab_count == 0
        assert _list(sa_sync_conn, search="Zzaffiche").total == 1

    def test_nom_et_prenom_separes_par_la_source(self, sa_sync_conn):
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        sa = insert_source_contribution(
            sa_sync_conn,
            source_record,
            raw_author_name=None,
            raw_last_name="Caldefie Chezet",
            raw_first_name="Zorphine",
            in_perimeter=True,
        )

        res = _list(sa_sync_conn, search="zorphine caldefie")
        [orphan] = [
            a for a in res.contributions if a.contribution_id == contribution_of(sa_sync_conn, sa)
        ]
        assert (orphan.full_name, orphan.last_name, orphan.first_name) == (
            "Zorphine Caldefie Chezet",
            "Caldefie Chezet",
            "Zorphine",
        )

    def test_filters_by_search(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(sa_sync_conn, publication)
        source_contribution_match = insert_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=0,
            raw_author_name="SpecialName",
            in_perimeter=True,
        )
        insert_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=1,
            raw_author_name="Autre",
            in_perimeter=True,
        )

        res = _list(sa_sync_conn, search="Special")
        assert [a.contribution_id for a in res.contributions] == [
            contribution_of(sa_sync_conn, source_contribution_match)
        ]

    def _labs_setup(self, conn):
        """Contribution source « Zzorph Avec » au labo LAB et à une équipe ; « Zzorph Autre » au labo AUTRE ; « Zzorph Sans » sans structure."""
        lab, other_lab, team = (
            insert_structure(conn, code, acronym=acronym, structure_type=stype)
            for code, acronym, stype in (
                ("ORPH-LAB", "LAB", "labo"),
                ("ORPH-OTHER", "AUTRE", "labo"),
                ("ORPH-TEAM", "EQ", "equipe"),
            )
        )
        source_record = insert_source_record(conn, insert_publication(conn))
        sa = insert_source_contribution(
            conn, source_record, author_position=0, raw_author_name="Zzorph Avec", in_perimeter=True
        )
        other = insert_source_contribution(
            conn,
            source_record,
            author_position=1,
            raw_author_name="Zzorph Autre",
            in_perimeter=True,
        )
        none = insert_source_contribution(
            conn, source_record, author_position=2, raw_author_name="Zzorph Sans", in_perimeter=True
        )
        add_source_contribution_structure(conn, sa, lab)
        add_source_contribution_structure(conn, sa, team)
        add_source_contribution_structure(conn, other, other_lab)
        _contribution(conn)
        return {
            "lab": lab,
            "other_lab": other_lab,
            "sa": sa,
            "sa_group": contribution_of(conn, sa),
            "other": contribution_of(conn, other),
            "none": contribution_of(conn, none),
        }

    def test_filters_by_lab(self, sa_sync_conn):
        ids = self._labs_setup(sa_sync_conn)

        def listed(**filters):
            return {
                a.contribution_id
                for a in _list(sa_sync_conn, search="Zzorph", **filters).contributions
            }

        assert listed(lab_ids=[ids["lab"]]) == {ids["sa_group"]}
        assert listed(lab_none=True) == {ids["none"]}
        assert listed(lab_ids=[ids["other_lab"]], lab_none=True) == {ids["other"], ids["none"]}

    def test_lab_facet_ignores_the_lab_filter(self, sa_sync_conn):
        ids = self._labs_setup(sa_sync_conn)

        facets = ContributionsQueries(sa_sync_conn).orphan_contributions_facets(
            filters=OrphanFilters(search="Zzorph", lab_ids=[ids["lab"]])
        )
        assert [(o.value, o.label, o.count) for o in facets.labs] == [
            (str(ids["other_lab"]), "AUTRE", 1),
            (str(ids["lab"]), "LAB", 1),
        ]
        assert facets.no_lab_count == 1

    def test_lists_labs_detected_in_the_source_contribution(self, sa_sync_conn):
        """Seuls les laboratoires des contributions sources de la contribution apparaissent, pas ceux des autres contributions sources de la publication ni les autres types de structure."""
        ids = self._labs_setup(sa_sync_conn)

        (row,) = _list(sa_sync_conn, search="Zzorph Avec").contributions
        assert [(lab_item.id, lab_item.label) for lab_item in row.labs] == [(ids["lab"], "LAB")]

    def test_un_laboratoire_atteint_par_deux_indices_compte_une_fois(self, sa_sync_conn):
        """« Zzorph Avec » atteint LAB par une adresse et par un ROR : une étiquette et un compte."""
        ids = self._labs_setup(sa_sync_conn)
        add_source_contribution_ror(sa_sync_conn, ids["sa"], ids["lab"])

        (row,) = _list(sa_sync_conn, search="Zzorph Avec").contributions
        facets = ContributionsQueries(sa_sync_conn).orphan_contributions_facets(
            filters=OrphanFilters(search="Zzorph")
        )

        assert [lab_item.id for lab_item in row.labs] == [ids["lab"]]
        assert (str(ids["lab"]), "LAB", 1) in [(o.value, o.label, o.count) for o in facets.labs]
