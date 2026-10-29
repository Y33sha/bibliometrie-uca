"""Tests d'intégration des lectures d'administration des personnes (`infrastructure.read_models.persons.admin`)."""

from functools import partial

import pytest
from sqlalchemy import text

from infrastructure.read_models.persons.queries import PersonsQueries
from tests.integration.helpers.alignment import (
    align_source_contributions,
    set_perimeter_author_contribution,
)
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import (
    insert_person,
    insert_person_identifier,
    insert_person_name_form,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import add_contribution_structure, insert_structure

# Forme de nom de source HAL.
_hal_name_form = partial(insert_person_name_form, sources=["hal"])

# Contribution de rôle auteur.
_author = partial(insert_contribution, roles=["author"])


def _person_source_contribution(conn, source_record, *, person_id, **source_contribution):
    """Contribution source décrite par `source_contribution`, seule contribution source d'une contribution rattachée à la personne `person_id`. Renvoie l'`id` de la contribution source."""
    source_contribution_id = insert_source_contribution(conn, source_record, **source_contribution)
    publication = conn.execute(
        text("SELECT publication_id FROM source_records WHERE id = :s"), {"s": source_record}
    ).scalar_one()
    contribution = align_source_contributions(
        conn, publication, [(source_contribution_id, source_record)]
    )
    set_perimeter_author_contribution(conn, contribution, person_id=person_id, mode="name")
    return source_contribution_id


class TestNameFormContributions:
    def test_returns_contributions_and_other_persons(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn, "Dupond")
        other = insert_person(sa_sync_conn, "Martin")
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(sa_sync_conn, publication)
        _person_source_contribution(
            sa_sync_conn,
            source_record,
            person_id=pid,
            author_name_normalized="dupond j",
            in_perimeter=True,
        )
        _hal_name_form(sa_sync_conn, pid, name_form="dupond j")
        _hal_name_form(sa_sync_conn, other, name_form="dupond j")

        res = PersonsQueries(sa_sync_conn).name_form_contributions(pid, "dupond j")
        assert len(res.contributions) >= 1
        other_ids = [p.person_id for p in res.other_persons]
        assert other in other_ids

    def test_exclut_les_personnes_chez_qui_la_forme_est_rejetee(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn, "Dupond")
        rejetee = insert_person(sa_sync_conn, "Martin")
        _hal_name_form(sa_sync_conn, pid, name_form="dupond j", status="pending")
        _hal_name_form(sa_sync_conn, rejetee, name_form="dupond j", status="rejected")

        res = PersonsQueries(sa_sync_conn).name_form_contributions(pid, "dupond j")

        assert res.other_persons == []


def test_compteur_modale_et_panneau_designent_les_memes_autres_porteurs(sa_sync_conn):
    """Le compteur d'une forme, la modale de détachement et le panneau des personnes partageant une forme désignent les mêmes autres personnes : ni celles chez qui la forme est rejetée, ni les personnes exclues."""
    pid = insert_person(sa_sync_conn, "Dupond")
    porteur = insert_person(sa_sync_conn, "Martin")
    forme_rejetee = insert_person(sa_sync_conn, "Durand")
    personne_rejetee = insert_person(sa_sync_conn, "Bernard", exclusion="not_a_person")
    for person, status in (
        (pid, "pending"),
        (porteur, "pending"),
        (forme_rejetee, "rejected"),
        (personne_rejetee, "pending"),
    ):
        _hal_name_form(sa_sync_conn, person, name_form="dupond j", status=status)

    (forme,) = PersonsQueries(sa_sync_conn).person_name_forms(pid)
    modale = PersonsQueries(sa_sync_conn).name_form_contributions(pid, "dupond j").other_persons
    panneau = PersonsQueries(sa_sync_conn).persons_sharing_name_form(pid)

    assert forme.shared_count == 1
    assert [p.person_id for p in modale] == [porteur]
    assert [p.person_id for p in panneau] == [porteur]


def test_une_forme_compte_les_publications_des_contributions_de_la_personne(sa_sync_conn):
    """Seules comptent les contributions sources des contributions de la personne : une contribution source de même forme hors de ses contributions ne compte pas."""
    pid = insert_person(sa_sync_conn, "Dupond")
    _hal_name_form(sa_sync_conn, pid, name_form="dupond j")
    for rank in range(2):
        _person_source_contribution(
            sa_sync_conn,
            insert_source_record(
                sa_sync_conn, insert_publication(sa_sync_conn), source_id=f"h-forme-{rank}"
            ),
            person_id=pid,
            author_name_normalized="dupond j",
        )
    insert_source_contribution(
        sa_sync_conn,
        insert_source_record(
            sa_sync_conn, insert_publication(sa_sync_conn), source_id="h-forme-hors-contribution"
        ),
        author_name_normalized="dupond j",
    )

    (forme,) = [
        f for f in PersonsQueries(sa_sync_conn).person_name_forms(pid) if f.name_form == "dupond j"
    ]
    contributions = (
        PersonsQueries(sa_sync_conn).name_form_contributions(pid, "dupond j").contributions
    )

    assert forme.publication_count == 2
    assert len(contributions) == 2


def _attribute(conn, person_id, id_type, id_value, status):
    """Attribue l'identifiant à la personne ; le statut `authenticated` exige le drapeau de l'import dédié."""
    if status == "authenticated":
        conn.execute(text("SET LOCAL app.orcid_authenticated_import = 'on'"))
    insert_person_identifier(conn, person_id, id_type=id_type, id_value=id_value, status=status)


class TestIdentifierConflicts:
    """Conflit d'identifiant : les contributions sources de deux personnes contiennent un identifiant attribué en attente à l'une d'elles. La lecture le calcule à la volée : aucune vue à rafraîchir."""

    def test_pair_sharing_orcid(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "Smith", first_name="John")
        p2 = insert_person(sa_sync_conn, "Smith", first_name="J")
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0001-2345-6789", "pending")
        _person_source_contribution(
            sa_sync_conn, source_record, identifiers={"orcid": "0000-0001-2345-6789"}, person_id=p1
        )
        _person_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=1,
            identifiers={"orcid": "0000-0001-2345-6789"},
            person_id=p2,
        )

        assert PersonsQueries(sa_sync_conn).identifier_conflicts_count() == 1
        res = PersonsQueries(sa_sync_conn).identifier_conflicts(page=1, per_page=50)
        assert res.total == 1
        pair = res.pairs[0]
        assert {pair.person_a.person_id, pair.person_b.person_id} == {p1, p2}
        assert [(s.id_type, s.id_value) for s in pair.shared_identifiers] == [
            ("orcid", "0000-0001-2345-6789")
        ]

    def test_neutralized_identifier_excluded(self, sa_sync_conn):
        """Une valeur que chaque contribution source neutralise ne fait pas de conflit, même en attente de validation."""
        p1 = insert_person(sa_sync_conn, "Brown", first_name="Anne")
        p2 = insert_person(sa_sync_conn, "Brown", first_name="A")
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0009-9999-9999", "pending")
        for position, person in ((0, p1), (1, p2)):
            _person_source_contribution(
                sa_sync_conn,
                source_record,
                author_position=position,
                identifiers={"orcid": "0000-0009-9999-9999"},
                person_id=person,
                neutralized_identifiers={"orcid": "shared"},
            )

        assert PersonsQueries(sa_sync_conn).identifier_conflicts_count() == 0

    @pytest.mark.parametrize("status", ["confirmed", "rejected", "authenticated"])
    def test_settled_attribution_excluded(self, sa_sync_conn, status):
        """Une attribution tranchée clôt le conflit, même si des contributions sources d'une autre personne contiennent la valeur."""
        p1 = insert_person(sa_sync_conn, "Veyssiere", first_name="Hugo")
        p2 = insert_person(sa_sync_conn, "Pinard", first_name="Celeste")
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0003-2202-7362", status)
        _person_source_contribution(
            sa_sync_conn, source_record, identifiers={"orcid": "0000-0003-2202-7362"}, person_id=p1
        )
        _person_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=1,
            identifiers={"orcid": "0000-0003-2202-7362"},
            person_id=p2,
        )

        assert PersonsQueries(sa_sync_conn).identifier_conflicts_count() == 0

    def test_unattributed_value_excluded(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "Lee", first_name="Anna")
        p2 = insert_person(sa_sync_conn, "Lee", first_name="A")
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        _person_source_contribution(
            sa_sync_conn, source_record, identifiers={"orcid": "0000-0002-1111-2222"}, person_id=p1
        )
        _person_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=1,
            identifiers={"orcid": "0000-0002-1111-2222"},
            person_id=p2,
        )

        assert PersonsQueries(sa_sync_conn).identifier_conflicts_count() == 0

    def test_excluded_person_excluded(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "Lee", first_name="Anna")
        p2 = insert_person(sa_sync_conn, "Lee", first_name="A", exclusion="out_of_perimeter")
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0002-1111-2222", "pending")
        _person_source_contribution(
            sa_sync_conn, source_record, identifiers={"orcid": "0000-0002-1111-2222"}, person_id=p1
        )
        _person_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=1,
            identifiers={"orcid": "0000-0002-1111-2222"},
            person_id=p2,
        )

        assert PersonsQueries(sa_sync_conn).identifier_conflicts_count() == 0


class TestNameDuplicates:
    """Paires aux noms compatibles, classées par recouvrement de réseau."""

    def _pair(self, res, a, b):
        return next(p for p in res.pairs if {p.person_a.person_id, p.person_b.person_id} == {a, b})

    def test_shared_coauthor_is_network_tier(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Dupont", first_name="J")
        b = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        coauthor = insert_person(sa_sync_conn, "Martin", first_name="Paul")
        pub1, pub2 = insert_publication(sa_sync_conn), insert_publication(sa_sync_conn)
        _author(sa_sync_conn, pub1, person_id=a)
        _author(sa_sync_conn, pub1, person_id=coauthor)
        _author(sa_sync_conn, pub2, person_id=b)
        _author(sa_sync_conn, pub2, person_id=coauthor)

        assert PersonsQueries(sa_sync_conn).name_duplicates_count() >= 1
        pair = self._pair(PersonsQueries(sa_sync_conn).name_duplicates(page=1, per_page=50), a, b)
        assert pair.overlaps.coauthors == 1

    def test_shared_lab_counts_and_lists_the_lab(self, sa_sync_conn):
        """Un laboratoire atteint par les contributions sources des contributions des deux personnes compte comme recouvrement et figure dans leur fiche allégée."""
        lab = insert_structure(sa_sync_conn, "LAB-DUP", acronym="LABDUP")
        a = insert_person(sa_sync_conn, "Lacombe", first_name="R")
        b = insert_person(sa_sync_conn, "Lacombe", first_name="Rémi")
        for person in (a, b):
            contribution = _author(sa_sync_conn, insert_publication(sa_sync_conn), person_id=person)
            add_contribution_structure(sa_sync_conn, contribution, lab)

        pair = self._pair(PersonsQueries(sa_sync_conn).name_duplicates(page=1, per_page=50), a, b)
        assert pair.overlaps.labs == 1
        for curated in (pair.person_a, pair.person_b):
            assert curated.labs == ["LABDUP"]
            assert curated.contribution_count == 1

    def test_disjoint_pair_has_no_overlap(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Bernard", first_name="M")
        b = insert_person(sa_sync_conn, "Bernard", first_name="Marie")

        pair = self._pair(PersonsQueries(sa_sync_conn).name_duplicates(page=1, per_page=50), a, b)
        assert (
            pair.overlaps.coauthors,
            pair.overlaps.shared_publications,
            pair.overlaps.labs,
            pair.overlaps.serials,
        ) == (0, 0, 0, 0)

    def test_compound_first_name_pairs_with_its_first_word(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Ferrand", first_name="Ludovic")
        b = insert_person(sa_sync_conn, "Ferrand", first_name="Ludovic S.")

        self._pair(PersonsQueries(sa_sync_conn).name_duplicates(page=1, per_page=50), a, b)

    def test_excluded_person_excluded(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Bekono", first_name="Nina")
        b = insert_person(sa_sync_conn, "Bekono", first_name="N", exclusion="not_a_person")

        res = PersonsQueries(sa_sync_conn).name_duplicates(page=1, per_page=50)
        assert all({p.person_a.person_id, p.person_b.person_id} != {a, b} for p in res.pairs)


class TestAmbiguousNameForms:
    """Formes de plusieurs personnes, avec au moins un lien à trancher."""

    def _forms(self, conn):
        return {
            f.name_form: f
            for f in PersonsQueries(conn).ambiguous_name_forms(page=1, per_page=500).forms
        }

    def test_forme_derivee_du_nom_hors_de_la_file(self, sa_sync_conn):
        """Une forme partagée seulement comme forme dérivée du nom de chaque personne n'attend aucune décision."""
        a = insert_person(sa_sync_conn, "Martin", first_name="Jean")
        b = insert_person(sa_sync_conn, "Martin", first_name="Jeanne")
        insert_person_name_form(sa_sync_conn, a, name_form="j martin", sources=["persons"])
        insert_person_name_form(sa_sync_conn, b, name_form="j martin", sources=["persons"])
        assert "j martin" not in self._forms(sa_sync_conn)

    def test_forme_derivee_du_nom_confirmee_d_office(self, sa_sync_conn):
        """Face à une forme bibliographique en attente, la forme dérivée du nom apparaît confirmée et verrouillée."""
        a = insert_person(sa_sync_conn, "Martin", first_name="Jean")
        b = insert_person(sa_sync_conn, "Martin", first_name="Jacques")
        insert_person_name_form(sa_sync_conn, a, name_form="j martin", sources=["persons"])
        _hal_name_form(sa_sync_conn, b, name_form="j martin")
        persons = {p.person_id: p for p in self._forms(sa_sync_conn)["j martin"].persons}
        assert (persons[a].canonical, persons[a].status) == (True, "confirmed")
        assert (persons[b].canonical, persons[b].status) == (False, "pending")

    def test_forme_rejetee_ne_compte_pas(self, sa_sync_conn):
        """En attente chez une personne, rejetée chez l'autre : la forme désigne une seule personne."""
        a = insert_person(sa_sync_conn, "Martin")
        b = insert_person(sa_sync_conn, "Durand")
        _hal_name_form(sa_sync_conn, a, name_form="j martin")
        _hal_name_form(sa_sync_conn, b, name_form="j martin", status="rejected")
        assert "j martin" not in self._forms(sa_sync_conn)

    def test_personne_rejetee_ne_compte_pas(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Martin")
        b = insert_person(sa_sync_conn, "Durand", exclusion="out_of_perimeter")
        _hal_name_form(sa_sync_conn, a, name_form="j martin")
        _hal_name_form(sa_sync_conn, b, name_form="j martin")
        assert "j martin" not in self._forms(sa_sync_conn)

    def test_seuls_les_porteurs_sont_affiches(self, sa_sync_conn):
        """Une forme ambiguë liste les personnes qui l'ont, sans celles chez qui elle est rejetée."""
        a = insert_person(sa_sync_conn, "Martin")
        b = insert_person(sa_sync_conn, "Martin", first_name="Jacques")
        c = insert_person(sa_sync_conn, "Durand")
        _hal_name_form(sa_sync_conn, a, name_form="j martin")
        _hal_name_form(sa_sync_conn, b, name_form="j martin", status="confirmed")
        _hal_name_form(sa_sync_conn, c, name_form="j martin", status="rejected")
        persons = self._forms(sa_sync_conn)["j martin"].persons
        assert sorted(p.person_id for p in persons) == sorted([a, b])
