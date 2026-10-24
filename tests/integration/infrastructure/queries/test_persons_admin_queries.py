"""Tests d'intégration pour `infrastructure.read_models.persons.admin`."""

from functools import partial

import pytest
from sqlalchemy import text

from infrastructure.read_models.persons.admin import (
    ambiguous_name_forms,
    identifier_conflicts,
    identifier_conflicts_count,
    name_duplicates,
    name_duplicates_count,
    name_form_contributions,
    persons_sharing_name_form,
)
from infrastructure.read_models.persons.list import person_name_forms
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


class TestNameFormContributions:
    def test_returns_contributions_and_other_persons(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn, "Dupond")
        other = insert_person(sa_sync_conn, "Martin")
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(sa_sync_conn, publication)
        insert_source_contribution(
            sa_sync_conn,
            source_record,
            person_id=pid,
            author_name_normalized="dupond j",
            in_perimeter=True,
        )
        _hal_name_form(sa_sync_conn, pid, name_form="dupond j")
        _hal_name_form(sa_sync_conn, other, name_form="dupond j")

        res = name_form_contributions(sa_sync_conn, pid, "dupond j")
        assert len(res.contributions) >= 1
        other_ids = [p.person_id for p in res.other_persons]
        assert other in other_ids

    def test_exclut_les_personnes_chez_qui_la_forme_est_rejetee(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn, "Dupond")
        rejetee = insert_person(sa_sync_conn, "Martin")
        _hal_name_form(sa_sync_conn, pid, name_form="dupond j", status="pending")
        _hal_name_form(sa_sync_conn, rejetee, name_form="dupond j", status="rejected")

        res = name_form_contributions(sa_sync_conn, pid, "dupond j")

        assert res.other_persons == []


def test_compteur_modale_et_panneau_designent_les_memes_autres_porteurs(sa_sync_conn):
    """Le compteur d'une forme, la modale de détachement et le panneau des personnes partageant une forme comptent les mêmes personnes."""
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

    (forme,) = person_name_forms(sa_sync_conn, pid)
    modale = name_form_contributions(sa_sync_conn, pid, "dupond j").other_persons
    panneau = persons_sharing_name_form(sa_sync_conn, pid)

    assert forme.shared_count == 1
    assert [p.person_id for p in modale] == [porteur]
    assert [p.person_id for p in panneau] == [porteur]


# Tests pour `hal_duplicate_accounts` déplacés vers
# `tests/integration/infrastructure/queries/test_hal_problems.py` —
# la query est maintenant exposée par PgHalProblemsQueries.


def _attribute(conn, person_id, id_type, id_value, status):
    """Attribution `person_identifiers` ; le statut `authenticated` exige le drapeau de l'import dédié."""
    if status == "authenticated":
        conn.execute(text("SET LOCAL app.orcid_authenticated_import = 'on'"))
    insert_person_identifier(conn, person_id, id_type=id_type, id_value=id_value, status=status)


class TestIdentifierConflicts:
    """La détection projette `(person_id, id_type, id_value)` à la volée depuis
    `source_contributions` ⋈ `contributor_information` : rien à rafraîchir, la lecture voit
    directement le seed de la transaction rollbackée du fixture."""

    def test_pair_sharing_orcid(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "Smith", first_name="John")
        p2 = insert_person(sa_sync_conn, "Smith", first_name="J")
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0001-2345-6789", "pending")
        insert_source_contribution(
            sa_sync_conn, source_record, identifiers={"orcid": "0000-0001-2345-6789"}, person_id=p1
        )
        insert_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=1,
            identifiers={"orcid": "0000-0001-2345-6789"},
            person_id=p2,
        )

        assert identifier_conflicts_count(sa_sync_conn) == 1
        res = identifier_conflicts(sa_sync_conn, page=1, per_page=50)
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
            insert_source_contribution(
                sa_sync_conn,
                source_record,
                author_position=position,
                identifiers={"orcid": "0000-0009-9999-9999"},
                person_id=person,
                neutralized_identifiers={"orcid": "shared"},
            )

        assert identifier_conflicts_count(sa_sync_conn) == 0

    @pytest.mark.parametrize("status", ["confirmed", "rejected", "authenticated"])
    def test_settled_attribution_excluded(self, sa_sync_conn, status):
        """Une attribution tranchée clôt le conflit, même si des contributions sources d'une autre personne contiennent la valeur."""
        p1 = insert_person(sa_sync_conn, "Veyssiere", first_name="Hugo")
        p2 = insert_person(sa_sync_conn, "Pinard", first_name="Celeste")
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0003-2202-7362", status)
        insert_source_contribution(
            sa_sync_conn, source_record, identifiers={"orcid": "0000-0003-2202-7362"}, person_id=p1
        )
        insert_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=1,
            identifiers={"orcid": "0000-0003-2202-7362"},
            person_id=p2,
        )

        assert identifier_conflicts_count(sa_sync_conn) == 0

    def test_unattributed_value_excluded(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "Lee", first_name="Anna")
        p2 = insert_person(sa_sync_conn, "Lee", first_name="A")
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        insert_source_contribution(
            sa_sync_conn, source_record, identifiers={"orcid": "0000-0002-1111-2222"}, person_id=p1
        )
        insert_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=1,
            identifiers={"orcid": "0000-0002-1111-2222"},
            person_id=p2,
        )

        assert identifier_conflicts_count(sa_sync_conn) == 0

    def test_excluded_person_excluded(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "Lee", first_name="Anna")
        p2 = insert_person(sa_sync_conn, "Lee", first_name="A", exclusion="out_of_perimeter")
        source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0002-1111-2222", "pending")
        insert_source_contribution(
            sa_sync_conn, source_record, identifiers={"orcid": "0000-0002-1111-2222"}, person_id=p1
        )
        insert_source_contribution(
            sa_sync_conn,
            source_record,
            author_position=1,
            identifiers={"orcid": "0000-0002-1111-2222"},
            person_id=p2,
        )

        assert identifier_conflicts_count(sa_sync_conn) == 0


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

        assert name_duplicates_count(sa_sync_conn) >= 1
        pair = self._pair(name_duplicates(sa_sync_conn, page=1, per_page=50), a, b)
        assert pair.overlaps.coauthors == 1

    def test_shared_lab_counts_and_lists_the_lab(self, sa_sync_conn):
        """Un laboratoire atteint par les membres des groupes des deux personnes compte comme recouvrement et figure dans leur fiche allégée."""
        lab = insert_structure(sa_sync_conn, "LAB-DUP", acronym="LABDUP")
        a = insert_person(sa_sync_conn, "Lacombe", first_name="R")
        b = insert_person(sa_sync_conn, "Lacombe", first_name="Rémi")
        for person in (a, b):
            contribution = _author(sa_sync_conn, insert_publication(sa_sync_conn), person_id=person)
            add_contribution_structure(sa_sync_conn, contribution, lab)

        pair = self._pair(name_duplicates(sa_sync_conn, page=1, per_page=50), a, b)
        assert pair.overlaps.labs == 1
        for curated in (pair.person_a, pair.person_b):
            assert curated.labs == ["LABDUP"]
            assert curated.contribution_count == 1

    def test_disjoint_pair_has_no_overlap(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Bernard", first_name="M")
        b = insert_person(sa_sync_conn, "Bernard", first_name="Marie")

        pair = self._pair(name_duplicates(sa_sync_conn, page=1, per_page=50), a, b)
        assert (
            pair.overlaps.coauthors,
            pair.overlaps.shared_publications,
            pair.overlaps.labs,
            pair.overlaps.journals,
        ) == (0, 0, 0, 0)

    def test_compound_first_name_pairs_with_its_first_word(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Ferrand", first_name="Ludovic")
        b = insert_person(sa_sync_conn, "Ferrand", first_name="Ludovic S.")

        self._pair(name_duplicates(sa_sync_conn, page=1, per_page=50), a, b)

    def test_excluded_person_excluded(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Bekono", first_name="Nina")
        b = insert_person(sa_sync_conn, "Bekono", first_name="N", exclusion="not_a_person")

        res = name_duplicates(sa_sync_conn, page=1, per_page=50)
        assert all({p.person_a.person_id, p.person_b.person_id} != {a, b} for p in res.pairs)


class TestAmbiguousNameForms:
    """Formes portées par plusieurs personnes, avec au moins un lien à trancher."""

    def _forms(self, conn):
        return {f.name_form: f for f in ambiguous_name_forms(conn, page=1, per_page=500).forms}

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
        """En attente chez une personne, rejetée chez l'autre : une seule personne porte la forme."""
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
        """Une forme ambiguë liste ses porteurs, sans les personnes chez qui la forme est rejetée."""
        a = insert_person(sa_sync_conn, "Martin")
        b = insert_person(sa_sync_conn, "Martin", first_name="Jacques")
        c = insert_person(sa_sync_conn, "Durand")
        _hal_name_form(sa_sync_conn, a, name_form="j martin")
        _hal_name_form(sa_sync_conn, b, name_form="j martin", status="confirmed")
        _hal_name_form(sa_sync_conn, c, name_form="j martin", status="rejected")
        persons = self._forms(sa_sync_conn)["j martin"].persons
        assert sorted(p.person_id for p in persons) == sorted([a, b])
