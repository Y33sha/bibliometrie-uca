"""Tâche `persons.resolve_contributions` : rattachement des contributions sans personne, sur vraie base."""

import logging

from sqlalchemy import text

from infrastructure.db.queues import Queue
from infrastructure.repositories import person_repository
from pipeline.transformation.persons.contribution_resolution import resolve_contributions
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.persons import (
    insert_person,
    insert_person_identifier,
    insert_person_name_form,
    insert_rejected_contribution,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import mark, queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_ORCID = "0000-0002-1825-0097"


def _contribution(conn, publication, members):
    """Contribution des contributions sources `(source, nom, identifiants, du périmètre)` de la publication."""
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
    return align_source_contributions(conn, publication, pairs)


def _person(conn, contribution):
    return tuple(
        conn.execute(
            text("SELECT person_id, resolution_mode FROM contributions WHERE id = :g"),
            {"g": contribution},
        ).one()
    )


def test_un_identifiant_d_une_contribution_source_rattache_la_contribution_hors_perimetre(
    sa_sync_conn,
):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="Jean")
    insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
    contribution = _contribution(
        conn,
        insert_publication(conn),
        [("crossref", "Jean Martin", {"orcid": _ORCID}, False), ("wos", "J. Martin", None, False)],
    )

    resolve_contributions(conn, logging.getLogger("test"))

    assert _person(conn, contribution) == (person, "orcid")


def _person_name(conn, person):
    return tuple(
        conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": person}
        ).one()
    )


class TestCreation:
    def test_un_nom_inconnu_du_perimetre_cree_une_personne(self, sa_sync_conn):
        conn = sa_sync_conn
        contribution = _contribution(
            conn, insert_publication(conn), [("hal", "Claire Durand", None, True)]
        )

        counts = resolve_contributions(conn, logging.getLogger("test"))

        person, mode = _person(conn, contribution)
        assert mode == "name"
        assert _person_name(conn, person) == ("Durand", "Claire")
        assert counts["created"] == 1

    def test_un_nom_inconnu_hors_perimetre_ne_cree_pas_de_personne(self, sa_sync_conn):
        conn = sa_sync_conn
        contribution = _contribution(
            conn, insert_publication(conn), [("hal", "Claire Durand", None, False)]
        )

        counts = resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (None, None)
        assert counts["created"] == 0

    def test_le_meme_nom_dans_une_autre_publication_rejoint_la_personne_creee(self, sa_sync_conn):
        conn = sa_sync_conn
        first = _contribution(
            conn, insert_publication(conn), [("hal", "Claire Durand", None, True)]
        )
        second = _contribution(
            conn, insert_publication(conn), [("openalex", "Claire Durand", None, True)]
        )

        counts = resolve_contributions(conn, logging.getLogger("test"))

        assert counts["created"] == 1
        assert _person(conn, first)[0] == _person(conn, second)[0] is not None

    def test_le_nom_vient_de_la_contribution_source_au_prenom_plein(self, sa_sync_conn):
        conn = sa_sync_conn
        contribution = _contribution(
            conn,
            insert_publication(conn),
            [("hal", "C. Durand", None, True), ("openalex", "Claire Durand", None, True)],
        )

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person_name(conn, _person(conn, contribution)[0]) == ("Durand", "Claire")


def test_une_personne_deja_rattachee_dans_la_publication_n_est_pas_reprise(sa_sync_conn):
    conn = sa_sync_conn
    person = person_repository(conn).create("Martin", "Jean")
    publication = insert_publication(conn)
    attached = _contribution(conn, publication, [("hal", "Jean Martin", None, True)])
    conn.execute(
        text("UPDATE contributions SET person_id = :p, resolution_mode = 'manual' WHERE id = :g"),
        {"p": person, "g": attached},
    )
    repeated = _contribution(conn, publication, [("openalex", "Jean Martin", None, True)])

    resolve_contributions(conn, logging.getLogger("test"))

    assert _person(conn, attached) == (person, "manual")
    assert _person(conn, repeated) == (None, None)


def _attach(conn, contribution, person, mode):
    conn.execute(
        text(
            "UPDATE contributions"
            " SET person_id = :p, resolution_mode = CAST(:m AS resolution_mode) WHERE id = :g"
        ),
        {"p": person, "g": contribution, "m": mode},
    )


def _pin_members(conn, contribution, person):
    """Épingle à `person` tous les contributions sources de la contribution."""
    conn.execute(
        text("""
            INSERT INTO confirmed_source_contributions (source_contribution_id, person_id)
            SELECT source_contribution_id, :p FROM aligned_source_contributions WHERE contribution_id = :g
        """),
        {"p": person, "g": contribution},
    )


class TestPins:
    def test_l_epinglage_remplace_une_personne_non_manuelle(self, sa_sync_conn):
        conn = sa_sync_conn
        by_name = insert_person(conn, "Martin", first_name="Jean")
        pinned = insert_person(conn, "Martin", first_name="Jeanne")
        contribution = _contribution(
            conn, insert_publication(conn), [("hal", "J. Martin", None, True)]
        )
        _attach(conn, contribution, by_name, "name")
        _pin_members(conn, contribution, pinned)

        counts = resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (pinned, "manual")
        assert counts["pinned"] == 1

    def test_l_epinglage_libere_l_autre_contribution_non_manuelle_de_la_personne(
        self, sa_sync_conn
    ):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        publication = insert_publication(conn)
        other = _contribution(conn, publication, [("openalex", "Jean Martin", None, True)])
        _attach(conn, other, person, "name")
        contribution = _contribution(conn, publication, [("hal", "J. Martin", None, True)])
        _pin_members(conn, contribution, person)

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (person, "manual")
        assert _person(conn, other)[0] != person

    def test_une_autre_contribution_manuelle_de_la_personne_l_emporte(self, sa_sync_conn):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        publication = insert_publication(conn)
        manual = _contribution(conn, publication, [("openalex", "Jean Martin", None, True)])
        _attach(conn, manual, person, "manual")
        contribution = _contribution(conn, publication, [("hal", "J. Martin", None, True)])
        _pin_members(conn, contribution, person)

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, manual) == (person, "manual")
        assert _person(conn, contribution)[0] != person

    def test_des_epinglages_contradictoires_laissent_la_contribution(self, sa_sync_conn):
        conn = sa_sync_conn
        first = insert_person(conn, "Martin", first_name="Jean")
        second = insert_person(conn, "Martin", first_name="Jeanne")
        contribution = _contribution(
            conn,
            insert_publication(conn),
            [("hal", "J. Martin", None, True), ("openalex", "J. Martin", None, True)],
        )
        _attach(conn, contribution, first, "name")
        members = (
            conn.execute(
                text(
                    "SELECT source_contribution_id FROM aligned_source_contributions"
                    " WHERE contribution_id = :g ORDER BY source_contribution_id"
                ),
                {"g": contribution},
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

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (first, "name")


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
    def test_les_identifiants_fiables_des_contributions_sources_sont_attribues_en_attente(
        self, sa_sync_conn
    ):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
        contribution = _contribution(
            conn,
            insert_publication(conn),
            [
                ("crossref", "Jean Martin", {"orcid": _ORCID}, True),
                ("hal", "Jean Martin", {"idref": "123456789"}, True),
            ],
        )

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (person, "orcid")
        assert ("idref", "123456789", "pending", "auto") in _identifiers_of(conn, person)

    def test_l_orcid_d_une_source_non_fiable_n_est_pas_attribue(self, sa_sync_conn):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
        _contribution(
            conn,
            insert_publication(conn),
            [
                ("crossref", "Jean Martin", {"orcid": _ORCID}, True),
                ("scanr", "Jean Martin", {"orcid": "0000-0001-5109-3700"}, True),
            ],
        )

        resolve_contributions(conn, logging.getLogger("test"))

        assert not any(v == "0000-0001-5109-3700" for _, v, _, _ in _identifiers_of(conn, person))


def test_le_prenom_reduit_est_complete_par_les_contributions_sources_des_contributions(
    sa_sync_conn,
):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="J.")
    contribution = _contribution(
        conn, insert_publication(conn), [("hal", "Jean Martin", None, True)]
    )
    _attach(conn, contribution, person, "manual")

    counts = resolve_contributions(conn, logging.getLogger("test"))

    assert counts["first_names_completed"] == 1
    assert (
        conn.execute(
            text("SELECT first_name FROM persons WHERE id = :p"), {"p": person}
        ).scalar_one()
        == "Jean"
    )


class TestPersonIndex:
    """L'index des personnes lu en base : attributions, formes de nom et verdicts, rejets."""

    def test_une_forme_de_nom_unique_rattache_la_contribution_du_perimetre(self, sa_sync_conn):
        conn = sa_sync_conn
        person = person_repository(conn).create("Martin", "Pierre")
        contribution = _contribution(
            conn, insert_publication(conn), [("hal", "Pierre Martin", None, True)]
        )

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (person, "name")

    def test_un_nom_inverse_rattache_par_la_forme_de_nom(self, sa_sync_conn):
        """Contribution source au nom et prénom inversés : sa forme « nom prénom » rejoint Pierre Martin."""
        conn = sa_sync_conn
        person = person_repository(conn).create("Martin", "Pierre")
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
        contribution = align_source_contributions(conn, publication, [(inverted, source_record)])

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (person, "name")

    def test_une_attribution_rejetee_ne_rattache_pas(self, sa_sync_conn):
        conn = sa_sync_conn
        person = person_repository(conn).create("Dupont", "Jean")
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="rejected")
        contribution = _contribution(
            conn, insert_publication(conn), [("openalex", "Jean Dupont", {"orcid": _ORCID}, False)]
        )

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (None, None)

    def test_une_forme_de_nom_rejetee_refuse_l_identifiant(self, sa_sync_conn):
        conn = sa_sync_conn
        person = person_repository(conn).create("Dupont", "Jean")
        insert_person_identifier(
            conn, person, id_type="hal_person_id", id_value="111222", status="confirmed"
        )
        insert_person_name_form(
            conn, person, name_form="jean dupond", sources=["hal"], status="rejected"
        )
        contribution = _contribution(
            conn,
            insert_publication(conn),
            [("hal", "Jean Dupond", {"hal_person_id": "111222"}, True)],
        )

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution)[0] != person

    def test_une_paire_rejetee_bloque_le_rattachement_par_identifiant(self, sa_sync_conn):
        conn = sa_sync_conn
        person = person_repository(conn).create("Dupont", "Jean")
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
        publication = insert_publication(conn)
        contribution = _contribution(
            conn, publication, [("openalex", "Jean Dupont", {"orcid": _ORCID}, True)]
        )
        insert_rejected_contribution(conn, publication, person_id=person, ignore_conflict=True)

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (None, None)

    def test_un_rejet_leve_l_ambiguite_d_une_forme_de_nom(self, sa_sync_conn):
        conn = sa_sync_conn
        rejected = person_repository(conn).create("Dupont", "Jean")
        kept = person_repository(conn).create("Dupont", "Jacques")
        publication = insert_publication(conn)
        contribution = _contribution(conn, publication, [("openalex", "J Dupont", None, True)])
        insert_rejected_contribution(conn, publication, person_id=rejected, ignore_conflict=True)

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (kept, "name")


def test_le_journal_compte_les_identifications_par_mode_et_les_creations(sa_sync_conn, caplog):
    conn = sa_sync_conn
    person = insert_person(conn, "Martin", first_name="Jean")
    insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
    _contribution(
        conn, insert_publication(conn), [("crossref", "Jean Martin", {"orcid": _ORCID}, True)]
    )
    _contribution(conn, insert_publication(conn), [("hal", "Claire Durand", None, True)])

    with caplog.at_level(logging.INFO):
        resolve_contributions(conn, logging.getLogger("test"))

    assert "  └─ 1 contribution identifiée, dont" in caplog.messages
    assert "     1 par ORCID" in caplog.messages
    assert "  └─ 1 personne créée" in caplog.messages


def test_un_role_sans_creation_ne_compte_pas_parmi_les_non_identifiees(sa_sync_conn, caplog):
    """Une contribution source du jury au nom inconnu reste sans personne sans être compté ; un auteur au nom inconnu fonde une personne."""
    conn = sa_sync_conn
    publication = insert_publication(conn)
    source_record = insert_source_record(conn, publication, source="theses", source_id="these-1")
    jury = insert_source_contribution(
        conn,
        source_record,
        source="theses",
        raw_author_name="Paul Durand",
        author_name_normalized="paul durand",
        in_perimeter=True,
        roles=["jury_member"],
    )
    align_source_contributions(conn, publication, [(jury, source_record)])
    _contribution(conn, insert_publication(conn), [("hal", "Claire Durand", None, True)])

    with caplog.at_level(logging.INFO):
        resolve_contributions(conn, logging.getLogger("test"))

    assert "  ├─ 1 contribution du périmètre non identifiée" in caplog.messages
    assert "  ├─ 0 indécidable" in caplog.messages


class TestResolutionQueue:
    """Une contribution en file garde sa personne jusqu'à sa redécision, qui ne l'écrit que si elle change."""

    def test_meme_personne_rien_n_est_ecrit(self, sa_sync_conn):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
        contribution = _contribution(
            conn, insert_publication(conn), [("crossref", "Jean Martin", {"orcid": _ORCID}, True)]
        )
        _attach(conn, contribution, person, "orcid")
        mark(conn, Queue.CONTRIBUTION_RESOLUTION, [contribution])

        counts = resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (person, "orcid")
        assert counts["written"] == 0
        assert queued(conn, Queue.CONTRIBUTION_RESOLUTION) == set()

    def test_une_autre_personne_designee_remplace_la_premiere(self, sa_sync_conn):
        conn = sa_sync_conn
        first = insert_person(conn, "Dupont", first_name="Paul")
        second = insert_person(conn, "Martin", first_name="Jean")
        insert_person_identifier(conn, second, id_type="orcid", id_value=_ORCID, status="confirmed")
        contribution = _contribution(
            conn, insert_publication(conn), [("crossref", "Jean Martin", {"orcid": _ORCID}, True)]
        )
        _attach(conn, contribution, first, "name")
        mark(conn, Queue.CONTRIBUTION_RESOLUTION, [contribution])

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (second, "orcid")

    def test_une_contribution_que_rien_ne_soutient_perd_sa_personne(self, sa_sync_conn):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        contribution = _contribution(
            conn, insert_publication(conn), [("hal", "Jean Martin", None, False)]
        )
        _attach(conn, contribution, person, "name")
        mark(conn, Queue.CONTRIBUTION_RESOLUTION, [contribution])

        counts = resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (None, None)
        assert counts["released"] == 1

    def test_la_personne_passe_a_la_contribution_mieux_appuyee_de_la_publication(
        self, sa_sync_conn
    ):
        """La contribution en file perd sa personne avant que la contribution rattachée par ORCID la reçoive.

        Régression : l'écriture du nouveau rattachement précédait le retrait de l'ancien et violait l'unicité de la personne dans la publication.
        """
        conn = sa_sync_conn
        person = person_repository(conn).create("Martin", "Jean")
        insert_person_identifier(conn, person, id_type="orcid", id_value=_ORCID, status="confirmed")
        publication = insert_publication(conn)
        by_name = _contribution(conn, publication, [("hal", "Jean Martin", None, True)])
        by_orcid = _contribution(
            conn, publication, [("crossref", "J. Martin", {"orcid": _ORCID}, True)]
        )
        _attach(conn, by_name, person, "name")
        mark(conn, Queue.CONTRIBUTION_RESOLUTION, [by_name])

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, by_orcid) == (person, "orcid")
        assert _person(conn, by_name) == (None, None)

    def test_une_contribution_manuelle_en_file_reste_rattachee(self, sa_sync_conn):
        conn = sa_sync_conn
        person = insert_person(conn, "Martin", first_name="Jean")
        contribution = _contribution(
            conn, insert_publication(conn), [("hal", "Claire Durand", None, False)]
        )
        _attach(conn, contribution, person, "manual")
        mark(conn, Queue.CONTRIBUTION_RESOLUTION, [contribution])

        resolve_contributions(conn, logging.getLogger("test"))

        assert _person(conn, contribution) == (person, "manual")
