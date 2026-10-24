"""Tâche `persons.resolve_groups` : rattachement des groupes sans personne, sur vraie base."""

import logging

from sqlalchemy import text

from application.services.persons.core import create_person
from infrastructure.repositories import person_repository
from pipeline.transformation.persons.groups import resolve_groups
from tests.integration.helpers.groups import insert_group
from tests.integration.helpers.persons import (
    insert_person,
    insert_person_identifier,
    insert_person_name_form,
    insert_rejected_contribution,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_ORCID = "0000-0002-1825-0097"


def _group(conn, publication, members):
    """Groupe des contributions sources `(source, nom, identifiants, du périmètre)` de la publication."""
    pairs = []
    for index, (source, name, identifiers, in_perimeter) in enumerate(members):
        source_record = insert_source_record(
            conn, publication, source=source, source_id=f"{source}-{publication}-{index}"
        )
        source_contribution = insert_source_contribution(
            conn,
            source_record,
            source=source,
            raw_author_name=name,
            author_name_normalized=name.lower(),
            identifiers=identifiers,
            in_perimeter=in_perimeter,
        )
        pairs.append((source_contribution, source_record))
    return insert_group(conn, publication, pairs)


def _person(conn, group):
    return tuple(
        conn.execute(
            text("SELECT person_id, resolution_mode FROM source_contribution_groups WHERE id = :g"),
            {"g": group},
        ).one()
    )


def test_un_identifiant_d_un_membre_rattache_le_groupe_hors_perimetre(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="Jean")
    insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
    group = _group(
        conn,
        insert_publication(conn),
        [("crossref", "Jean Martin", {"orcid": _ORCID}, False), ("wos", "J. Martin", None, False)],
    )

    resolve_groups(conn, logging.getLogger("test"))

    assert _person(conn, group) == (person, "orcid")


def _person_name(conn, person):
    return tuple(
        conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": person}
        ).one()
    )


class TestCreation:
    def test_un_nom_inconnu_du_perimetre_cree_une_personne(self, sa_sync_conn):
        conn = sa_sync_conn
        group = _group(conn, insert_publication(conn), [("hal", "Claire Durand", None, True)])

        counts = resolve_groups(conn, logging.getLogger("test"))

        person, mode = _person(conn, group)
        assert mode == "name"
        assert _person_name(conn, person) == ("Durand", "Claire")
        assert counts["created"] == 1

    def test_un_nom_inconnu_hors_perimetre_ne_cree_pas_de_personne(self, sa_sync_conn):
        conn = sa_sync_conn
        group = _group(conn, insert_publication(conn), [("hal", "Claire Durand", None, False)])

        counts = resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (None, None)
        assert counts["created"] == 0

    def test_le_meme_nom_dans_une_autre_publication_rejoint_la_personne_creee(self, sa_sync_conn):
        conn = sa_sync_conn
        first = _group(conn, insert_publication(conn), [("hal", "Claire Durand", None, True)])
        second = _group(conn, insert_publication(conn), [("openalex", "Claire Durand", None, True)])

        counts = resolve_groups(conn, logging.getLogger("test"))

        assert counts["created"] == 1
        assert _person(conn, first)[0] == _person(conn, second)[0] is not None

    def test_le_nom_vient_du_membre_au_prenom_plein(self, sa_sync_conn):
        conn = sa_sync_conn
        group = _group(
            conn,
            insert_publication(conn),
            [("hal", "C. Durand", None, True), ("openalex", "Claire Durand", None, True)],
        )

        resolve_groups(conn, logging.getLogger("test"))

        assert _person_name(conn, _person(conn, group)[0]) == ("Durand", "Claire")


def test_une_personne_deja_rattachee_dans_la_publication_n_est_pas_reprise(sa_sync_conn):
    conn = sa_sync_conn
    person = create_person("Martin", "Jean", repo=person_repository(conn))
    publication = insert_publication(conn)
    attached = _group(conn, publication, [("hal", "Jean Martin", None, True)])
    conn.execute(
        text(
            "UPDATE source_contribution_groups SET person_id = :p, resolution_mode = 'manual'"
            " WHERE id = :g"
        ),
        {"p": person, "g": attached},
    )
    repeated = _group(conn, publication, [("openalex", "Jean Martin", None, True)])

    resolve_groups(conn, logging.getLogger("test"))

    assert _person(conn, attached) == (person, "manual")
    assert _person(conn, repeated) == (None, None)


def _attach(conn, group, person, mode):
    conn.execute(
        text(
            "UPDATE source_contribution_groups"
            " SET person_id = :p, resolution_mode = CAST(:m AS group_resolution_mode) WHERE id = :g"
        ),
        {"p": person, "g": group, "m": mode},
    )


def _pin_members(conn, group, person):
    """Épingle à `person` tous les membres du groupe."""
    conn.execute(
        text("""
            INSERT INTO confirmed_source_contributions (source_contribution_id, person_id)
            SELECT source_contribution_id, :p FROM source_contribution_group_members WHERE group_id = :g
        """),
        {"p": person, "g": group},
    )


class TestPins:
    def test_l_epinglage_remplace_une_personne_non_manuelle(self, sa_sync_conn):
        conn = sa_sync_conn
        by_name = insert_person(conn, "Martin", first_name="Jean")
        pinned = insert_person(conn, "Martin", first_name="Jeanne")
        group = _group(conn, insert_publication(conn), [("hal", "J. Martin", None, True)])
        _attach(conn, group, by_name, "name")
        _pin_members(conn, group, pinned)

        counts = resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (pinned, "manual")
        assert counts["pinned"] == 1

    def test_l_epinglage_libere_l_autre_groupe_non_manuel_de_la_personne(self, sa_sync_conn):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        publication = insert_publication(conn)
        other = _group(conn, publication, [("openalex", "Jean Martin", None, True)])
        _attach(conn, other, person, "name")
        group = _group(conn, publication, [("hal", "J. Martin", None, True)])
        _pin_members(conn, group, person)

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (person, "manual")
        assert _person(conn, other)[0] != person

    def test_un_autre_groupe_manuel_de_la_personne_l_emporte(self, sa_sync_conn):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        publication = insert_publication(conn)
        manual = _group(conn, publication, [("openalex", "Jean Martin", None, True)])
        _attach(conn, manual, person, "manual")
        group = _group(conn, publication, [("hal", "J. Martin", None, True)])
        _pin_members(conn, group, person)

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, manual) == (person, "manual")
        assert _person(conn, group)[0] != person

    def test_des_epinglages_contradictoires_laissent_le_groupe(self, sa_sync_conn):
        conn = sa_sync_conn
        first = insert_person(conn, "Martin", first_name="Jean")
        second = insert_person(conn, "Martin", first_name="Jeanne")
        group = _group(
            conn,
            insert_publication(conn),
            [("hal", "J. Martin", None, True), ("openalex", "J. Martin", None, True)],
        )
        _attach(conn, group, first, "name")
        members = (
            conn.execute(
                text(
                    "SELECT source_contribution_id FROM source_contribution_group_members"
                    " WHERE group_id = :g ORDER BY source_contribution_id"
                ),
                {"g": group},
            )
            .scalars()
            .all()
        )
        for member, person in zip(members, (first, second), strict=True):
            conn.execute(
                text(
                    "INSERT INTO confirmed_source_contributions (source_contribution_id, person_id)"
                    " VALUES (:s, :p)"
                ),
                {"s": member, "p": person},
            )

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (first, "name")


def _identifiers_of(conn, person):
    return {
        (r.id_type, r.id_value, r.status, r.source)
        for r in conn.execute(
            text(
                "SELECT id_type::text, id_value, status::text, source::text"
                " FROM person_identifiers WHERE person_id = :p"
            ),
            {"p": person},
        )
    }


class TestIdentifierAttribution:
    def test_les_identifiants_fiables_des_membres_sont_attribues_en_attente(self, sa_sync_conn):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
        group = _group(
            conn,
            insert_publication(conn),
            [
                ("crossref", "Jean Martin", {"orcid": _ORCID}, True),
                ("hal", "Jean Martin", {"idref": "123456789"}, True),
            ],
        )

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (person, "orcid")
        assert ("idref", "123456789", "pending", "auto") in _identifiers_of(conn, person)

    def test_l_orcid_d_une_source_non_fiable_n_est_pas_attribue(self, sa_sync_conn):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
        _group(
            conn,
            insert_publication(conn),
            [
                ("crossref", "Jean Martin", {"orcid": _ORCID}, True),
                ("scanr", "Jean Martin", {"orcid": "0000-0001-5109-3700"}, True),
            ],
        )

        resolve_groups(conn, logging.getLogger("test"))

        assert not any(v == "0000-0001-5109-3700" for _, v, _, _ in _identifiers_of(conn, person))


def test_le_prenom_reduit_est_complete_par_les_membres_des_groupes(sa_sync_conn):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="J.")
    group = _group(conn, insert_publication(conn), [("hal", "Jean Martin", None, True)])
    _attach(conn, group, person, "manual")

    counts = resolve_groups(conn, logging.getLogger("test"))

    assert counts["first_names_completed"] == 1
    assert (
        conn.execute(
            text("SELECT first_name FROM persons WHERE id = :p"), {"p": person}
        ).scalar_one()
        == "Jean"
    )


class TestPersonIndex:
    """L'index des personnes lu en base : attributions, formes de nom et verdicts, rejets."""

    def test_une_forme_de_nom_unique_rattache_le_groupe_du_perimetre(self, sa_sync_conn):
        conn = sa_sync_conn
        person = create_person("Martin", "Pierre", repo=person_repository(conn))
        group = _group(conn, insert_publication(conn), [("hal", "Pierre Martin", None, True)])

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (person, "name")

    def test_un_nom_inverse_rattache_par_la_forme_de_nom(self, sa_sync_conn):
        """Contribution source au nom et prénom inversés : sa forme « nom prénom » rejoint Pierre Martin."""
        conn = sa_sync_conn
        person = create_person("Martin", "Pierre", repo=person_repository(conn))
        publication = insert_publication(conn)
        source_record = insert_source_record(conn, publication, source="crossref")
        inverted = insert_source_contribution(
            conn,
            source_record,
            source="crossref",
            raw_last_name="Pierre",
            raw_first_name="Martin",
            author_name_normalized="martin pierre",
            in_perimeter=True,
        )
        group = insert_group(conn, publication, [(inverted, source_record)])

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (person, "name")

    def test_une_attribution_rejetee_ne_rattache_pas(self, sa_sync_conn):
        conn = sa_sync_conn
        person = create_person("Dupont", "Jean", repo=person_repository(conn))
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="rejected")
        group = _group(
            conn, insert_publication(conn), [("openalex", "Jean Dupont", {"orcid": _ORCID}, False)]
        )

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (None, None)

    def test_une_forme_de_nom_rejetee_refuse_l_identifiant(self, sa_sync_conn):
        conn = sa_sync_conn
        person = create_person("Dupont", "Jean", repo=person_repository(conn))
        insert_person_identifier(
            conn, person, id_type="hal_person_id", id_value="111222", status="confirmed"
        )
        insert_person_name_form(
            conn, person, name_form="jean dupond", sources=["hal"], status="rejected"
        )
        group = _group(
            conn,
            insert_publication(conn),
            [("hal", "Jean Dupond", {"hal_person_id": "111222"}, True)],
        )

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group)[0] != person

    def test_une_paire_rejetee_bloque_le_rattachement_par_identifiant(self, sa_sync_conn):
        conn = sa_sync_conn
        person = create_person("Dupont", "Jean", repo=person_repository(conn))
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
        publication = insert_publication(conn)
        group = _group(conn, publication, [("openalex", "Jean Dupont", {"orcid": _ORCID}, True)])
        insert_rejected_contribution(conn, publication, person_id=person, ignore_conflict=True)

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (None, None)

    def test_un_rejet_leve_l_ambiguite_d_une_forme_de_nom(self, sa_sync_conn):
        conn = sa_sync_conn
        rejected = create_person("Dupont", "Jean", repo=person_repository(conn))
        kept = create_person("Dupont", "Jacques", repo=person_repository(conn))
        publication = insert_publication(conn)
        group = _group(conn, publication, [("openalex", "J Dupont", None, True)])
        insert_rejected_contribution(conn, publication, person_id=rejected, ignore_conflict=True)

        resolve_groups(conn, logging.getLogger("test"))

        assert _person(conn, group) == (kept, "name")


def test_le_journal_compte_les_identifications_par_mode_et_les_creations(sa_sync_conn, caplog):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="Jean")
    insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
    _group(conn, insert_publication(conn), [("crossref", "Jean Martin", {"orcid": _ORCID}, True)])
    _group(conn, insert_publication(conn), [("hal", "Claire Durand", None, True)])

    with caplog.at_level(logging.INFO):
        resolve_groups(conn, logging.getLogger("test"))

    assert "  └─ 1 contribution identifiée, dont" in caplog.messages
    assert "     1 par ORCID" in caplog.messages
    assert "  └─ 1 personne créée" in caplog.messages
