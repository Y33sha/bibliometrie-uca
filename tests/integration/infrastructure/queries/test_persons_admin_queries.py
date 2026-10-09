"""Tests d'intégration pour `infrastructure.read_models.persons.admin`."""

import json

import pytest
from sqlalchemy import text

from infrastructure.read_models.persons.admin import (
    ambiguous_name_forms,
    identifier_conflicts,
    identifier_conflicts_count,
    name_duplicates,
    name_duplicates_count,
    name_form_authorships,
    persons_sharing_name_form,
)
from infrastructure.read_models.persons.list import person_name_forms
from tests.integration.helpers.authorships import upsert_identity
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication


def _create_authorship(conn, pub_id, person_id):
    conn.execute(
        text(
            "INSERT INTO authorships (publication_id, person_id, roles) "
            "VALUES (:p, :pe, ARRAY['author']::text[])"
        ),
        {"p": pub_id, "pe": person_id},
    )


def _create_sd(conn, pub_id, source="hal", source_id="h1"):
    row = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES (:src, :sid, 'X', :pid) RETURNING id"
        ),
        {"src": source, "sid": source_id, "pid": pub_id},
    ).one()
    return row.id


def _create_sa(
    conn,
    sd,
    *,
    source="hal",
    author_position=0,
    person_id=None,
    in_perimeter=True,
    author_name_normalized=None,
    raw_author_name="X",
    roles=None,
):
    identity_id = upsert_identity(conn, author_name_normalized=author_name_normalized)
    row = conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position,
                 person_id, in_perimeter, identity_id, raw_author_name,
                 roles)
            VALUES (:src, :sd, :pos, :pid, :inp, :iid, :raw,
                    COALESCE(:roles, ARRAY['author']::text[]))
            RETURNING id
        """),
        {
            "src": source,
            "sd": sd,
            "pos": author_position,
            "pid": person_id,
            "inp": in_perimeter,
            "iid": identity_id,
            "raw": raw_author_name,
            "roles": roles,
        },
    ).one()
    return row.id


class TestNameFormAuthorships:
    def test_returns_authorships_and_other_persons(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn, "Dupond")
        other = insert_person(sa_sync_conn, "Martin")
        pub = insert_publication(sa_sync_conn)
        sd = _create_sd(sa_sync_conn, pub)
        _create_sa(sa_sync_conn, sd, person_id=pid, author_name_normalized="dupond j")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources) "
                "VALUES ('dupond j', :pid, ARRAY['hal']), "
                "       ('dupond j', :other, ARRAY['hal'])"
            ),
            {"pid": pid, "other": other},
        )

        res = name_form_authorships(sa_sync_conn, pid, "dupond j")
        assert len(res.authorships) >= 1
        other_ids = [p.person_id for p in res.other_persons]
        assert other in other_ids

    def test_exclut_les_personnes_chez_qui_la_forme_est_rejetee(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn, "Dupond")
        rejetee = insert_person(sa_sync_conn, "Martin")
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
                "VALUES ('dupond j', :pid, ARRAY['hal'], 'pending'), "
                "       ('dupond j', :rejetee, ARRAY['hal'], 'rejected')"
            ),
            {"pid": pid, "rejetee": rejetee},
        )

        res = name_form_authorships(sa_sync_conn, pid, "dupond j")

        assert res.other_persons == []


def test_compteur_modale_et_panneau_designent_les_memes_autres_porteurs(sa_sync_conn):
    """Le compteur d'une forme, la modale de détachement et le panneau des personnes partageant une forme comptent les mêmes personnes."""
    pid = insert_person(sa_sync_conn, "Dupond")
    porteur = insert_person(sa_sync_conn, "Martin")
    forme_rejetee = insert_person(sa_sync_conn, "Durand")
    personne_rejetee = insert_person(sa_sync_conn, "Bernard", exclusion="not_a_person")
    sa_sync_conn.execute(
        text(
            "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
            "VALUES ('dupond j', :pid, ARRAY['hal'], 'pending'), "
            "       ('dupond j', :porteur, ARRAY['hal'], 'pending'), "
            "       ('dupond j', :forme_rejetee, ARRAY['hal'], 'rejected'), "
            "       ('dupond j', :personne_rejetee, ARRAY['hal'], 'pending')"
        ),
        {
            "pid": pid,
            "porteur": porteur,
            "forme_rejetee": forme_rejetee,
            "personne_rejetee": personne_rejetee,
        },
    )

    (forme,) = person_name_forms(sa_sync_conn, pid)
    modale = name_form_authorships(sa_sync_conn, pid, "dupond j").other_persons
    panneau = persons_sharing_name_form(sa_sync_conn, pid)

    assert forme.shared_count == 1
    assert [p.person_id for p in modale] == [porteur]
    assert [p.person_id for p in panneau] == [porteur]


# Tests pour `hal_duplicate_accounts` déplacés vers
# `tests/integration/infrastructure/queries/test_hal_problems.py` —
# la query est maintenant exposée par PgHalProblemsQueries.


def _sa_with_identifiers(conn, sd, position, person_id, identifiers, neutralized=None):
    """Signature portant `identifiers` : l'identité (nom normalisé absent + identifiants) est
    upsertée dans `author_identifying_keys`, la signature la référence par `identity_id` et
    porte la carte `neutralized` de ses identifiants neutralisés."""
    identity_id = upsert_identity(conn, person_identifiers=identifiers)
    conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, person_id,
                 raw_author_name, identity_id, neutralized_identifiers)
            VALUES ('hal', :sd, :pos, :pid, 'X', :iid, CAST(:neu AS jsonb))
        """),
        {
            "sd": sd,
            "pos": position,
            "pid": person_id,
            "iid": identity_id,
            "neu": json.dumps(neutralized) if neutralized else None,
        },
    )


def _attribute(conn, person_id, id_type, id_value, status):
    """Attribution `person_identifiers` ; le statut `authenticated` exige le drapeau de l'import dédié."""
    if status == "authenticated":
        conn.execute(text("SET LOCAL app.orcid_authenticated_import = 'on'"))
    conn.execute(
        text(
            "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
            "VALUES (:pid, :t, :v, 'auto', CAST(:s AS identifier_status))"
        ),
        {"pid": person_id, "t": id_type, "v": id_value, "s": status},
    )


class TestIdentifierConflicts:
    """La détection projette `(person_id, id_type, id_value)` à la volée depuis
    `source_authorships` ⋈ `author_identifying_keys` : rien à rafraîchir, la lecture voit
    directement le seed de la transaction rollbackée du fixture."""

    def test_pair_sharing_orcid(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "Smith", first_name="John")
        p2 = insert_person(sa_sync_conn, "Smith", first_name="J")
        sd = _create_sd(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0001-2345-6789", "pending")
        _sa_with_identifiers(sa_sync_conn, sd, 0, p1, {"orcid": "0000-0001-2345-6789"})
        _sa_with_identifiers(sa_sync_conn, sd, 1, p2, {"orcid": "0000-0001-2345-6789"})

        assert identifier_conflicts_count(sa_sync_conn) == 1
        res = identifier_conflicts(sa_sync_conn, page=1, per_page=50)
        assert res.total == 1
        pair = res.pairs[0]
        assert {pair.person_a.person_id, pair.person_b.person_id} == {p1, p2}
        assert [(s.id_type, s.id_value) for s in pair.shared_identifiers] == [
            ("orcid", "0000-0001-2345-6789")
        ]

    def test_neutralized_identifier_excluded(self, sa_sync_conn):
        """Une valeur que chaque signature neutralise ne fait pas de conflit, même en attente de validation."""
        p1 = insert_person(sa_sync_conn, "Brown", first_name="Anne")
        p2 = insert_person(sa_sync_conn, "Brown", first_name="A")
        sd = _create_sd(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0009-9999-9999", "pending")
        for position, person in ((0, p1), (1, p2)):
            _sa_with_identifiers(
                sa_sync_conn,
                sd,
                position,
                person,
                {"orcid": "0000-0009-9999-9999"},
                neutralized={"orcid": "shared"},
            )

        assert identifier_conflicts_count(sa_sync_conn) == 0

    @pytest.mark.parametrize("status", ["confirmed", "rejected", "authenticated"])
    def test_settled_attribution_excluded(self, sa_sync_conn, status):
        """Une attribution tranchée clôt le conflit, même si des signatures d'une autre personne portent la valeur."""
        p1 = insert_person(sa_sync_conn, "Veyssiere", first_name="Hugo")
        p2 = insert_person(sa_sync_conn, "Pinard", first_name="Celeste")
        sd = _create_sd(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0003-2202-7362", status)
        _sa_with_identifiers(sa_sync_conn, sd, 0, p1, {"orcid": "0000-0003-2202-7362"})
        _sa_with_identifiers(sa_sync_conn, sd, 1, p2, {"orcid": "0000-0003-2202-7362"})

        assert identifier_conflicts_count(sa_sync_conn) == 0

    def test_unattributed_value_excluded(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "Lee", first_name="Anna")
        p2 = insert_person(sa_sync_conn, "Lee", first_name="A")
        sd = _create_sd(sa_sync_conn, insert_publication(sa_sync_conn))
        _sa_with_identifiers(sa_sync_conn, sd, 0, p1, {"orcid": "0000-0002-1111-2222"})
        _sa_with_identifiers(sa_sync_conn, sd, 1, p2, {"orcid": "0000-0002-1111-2222"})

        assert identifier_conflicts_count(sa_sync_conn) == 0

    def test_excluded_person_excluded(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "Lee", first_name="Anna")
        p2 = insert_person(sa_sync_conn, "Lee", first_name="A", exclusion="out_of_perimeter")
        sd = _create_sd(sa_sync_conn, insert_publication(sa_sync_conn))
        _attribute(sa_sync_conn, p1, "orcid", "0000-0002-1111-2222", "pending")
        _sa_with_identifiers(sa_sync_conn, sd, 0, p1, {"orcid": "0000-0002-1111-2222"})
        _sa_with_identifiers(sa_sync_conn, sd, 1, p2, {"orcid": "0000-0002-1111-2222"})

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
        _create_authorship(sa_sync_conn, pub1, a)
        _create_authorship(sa_sync_conn, pub1, coauthor)
        _create_authorship(sa_sync_conn, pub2, b)
        _create_authorship(sa_sync_conn, pub2, coauthor)

        assert name_duplicates_count(sa_sync_conn) >= 1
        pair = self._pair(name_duplicates(sa_sync_conn, page=1, per_page=50), a, b)
        assert pair.overlaps.coauthors == 1

    def test_disjoint_pair_has_no_overlap(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Bernard", first_name="M")
        b = insert_person(sa_sync_conn, "Bernard", first_name="Marie")

        pair = self._pair(name_duplicates(sa_sync_conn, page=1, per_page=50), a, b)
        assert (
            pair.overlaps.coauthors,
            pair.overlaps.shared_pubs,
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

    def _form(self, conn, form, person_id, *, sources="{hal}", status="pending"):
        conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
                "VALUES (:f, :p, CAST(:src AS text[]), CAST(:st AS identifier_status))"
            ),
            {"f": form, "p": person_id, "src": sources, "st": status},
        )

    def _forms(self, conn):
        return {f.name_form: f for f in ambiguous_name_forms(conn, page=1, per_page=500).forms}

    def test_forme_derivee_du_nom_hors_de_la_file(self, sa_sync_conn):
        """Une forme partagée seulement comme forme dérivée du nom de chaque personne n'attend aucune décision."""
        a = insert_person(sa_sync_conn, "Martin", first_name="Jean")
        b = insert_person(sa_sync_conn, "Martin", first_name="Jeanne")
        self._form(sa_sync_conn, "j martin", a, sources="{persons}")
        self._form(sa_sync_conn, "j martin", b, sources="{persons}")
        assert "j martin" not in self._forms(sa_sync_conn)

    def test_forme_derivee_du_nom_confirmee_d_office(self, sa_sync_conn):
        """Face à une forme bibliographique en attente, la forme dérivée du nom apparaît confirmée et verrouillée."""
        a = insert_person(sa_sync_conn, "Martin", first_name="Jean")
        b = insert_person(sa_sync_conn, "Martin", first_name="Jacques")
        self._form(sa_sync_conn, "j martin", a, sources="{persons}")
        self._form(sa_sync_conn, "j martin", b)
        persons = {p.person_id: p for p in self._forms(sa_sync_conn)["j martin"].persons}
        assert (persons[a].canonical, persons[a].status) == (True, "confirmed")
        assert (persons[b].canonical, persons[b].status) == (False, "pending")

    def test_forme_rejetee_ne_compte_pas(self, sa_sync_conn):
        """En attente chez une personne, rejetée chez l'autre : une seule personne porte la forme."""
        a = insert_person(sa_sync_conn, "Martin")
        b = insert_person(sa_sync_conn, "Durand")
        self._form(sa_sync_conn, "j martin", a)
        self._form(sa_sync_conn, "j martin", b, status="rejected")
        assert "j martin" not in self._forms(sa_sync_conn)

    def test_personne_rejetee_ne_compte_pas(self, sa_sync_conn):
        a = insert_person(sa_sync_conn, "Martin")
        b = insert_person(sa_sync_conn, "Durand", exclusion="out_of_perimeter")
        self._form(sa_sync_conn, "j martin", a)
        self._form(sa_sync_conn, "j martin", b)
        assert "j martin" not in self._forms(sa_sync_conn)

    def test_seuls_les_porteurs_sont_affiches(self, sa_sync_conn):
        """Une forme ambiguë liste ses porteurs, sans les personnes chez qui la forme est rejetée."""
        a = insert_person(sa_sync_conn, "Martin")
        b = insert_person(sa_sync_conn, "Martin", first_name="Jacques")
        c = insert_person(sa_sync_conn, "Durand")
        self._form(sa_sync_conn, "j martin", a)
        self._form(sa_sync_conn, "j martin", b, status="confirmed")
        self._form(sa_sync_conn, "j martin", c, status="rejected")
        persons = self._forms(sa_sync_conn)["j martin"].persons
        assert sorted(p.person_id for p in persons) == sorted([a, b])
