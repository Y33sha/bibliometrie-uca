"""Arbitrage des identifiants de personne au niveau des contributions : vote des contributions sur les conflits d'attribution, libération des contributions après un transfert ou une neutralisation `misplaced`."""

import logging

from sqlalchemy import text

from infrastructure.db.queues import Queue
from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.persons import insert_person, insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_LOG = logging.getLogger("test")
_ORCID = "0000-0002-1825-0097"


def _contribution(conn, person, mode, *, name="jean martin", source="crossref", orcid=_ORCID):
    """Insère une contribution formée d'une seule contribution source, seul auteur d'une publication, rattachée à `person` par `mode`. La contribution source contient l'ORCID `orcid`."""
    publication = insert_publication(conn)
    source_record = insert_source_record(
        conn, publication, source=source, source_id=f"{source}-{publication}"
    )
    source_contribution = insert_source_contribution(
        conn,
        source_record,
        source=source,
        raw_author_name=name,
        author_name_normalized=name,
        identifiers={"orcid": orcid},
    )
    contribution = align_source_contributions(
        conn, publication, [(source_contribution, source_record)]
    )
    conn.execute(
        text(
            "UPDATE contributions"
            " SET person_id = :p, resolution_mode = CAST(:m AS resolution_mode) WHERE id = :g"
        ),
        {"p": person, "g": contribution, "m": mode},
    )
    return contribution


def _contributions(conn, count, person, mode, **kwargs):
    return [_contribution(conn, person, mode, **kwargs) for _ in range(count)]


def _arbitrate(conn):
    return arbitrate_identifier_conflicts(conn, _LOG, repo=PgPersonRepository(conn))


def _orcid_owner(conn):
    return conn.execute(
        text("SELECT person_id FROM person_identifiers WHERE id_type = 'orcid' AND id_value = :v"),
        {"v": _ORCID},
    ).scalar_one()


def _person_of(conn, contribution):
    return tuple(
        conn.execute(
            text("SELECT person_id, resolution_mode FROM contributions WHERE id = :g"),
            {"g": contribution},
        ).one()
    )


def _persons(conn, owner_name=("Martin", "Jean"), other_name=("Martin", "Jeanne")):
    """Insère le titulaire de l'ORCID en `pending`, et une autre personne."""
    owner = insert_person(conn, owner_name[0], first_name=owner_name[1])
    other = insert_person(conn, other_name[0], first_name=other_name[1])
    insert_person_identifier(conn, owner, id_type="orcid", id_value=_ORCID, status="pending")
    return owner, other


class TestConflicts:
    def test_la_majorite_des_voix_transfere_et_marque_les_contributions_du_titulaire(
        self, sa_sync_conn
    ):
        """Le titulaire a quatre voix (deux contributions rattachées par l'ORCID, une contribution manuelle, une contribution rattachée par IdRef), l'autre personne cinq : l'ORCID passe à l'autre personne. Seules les contributions du titulaire rattachées par l'ORCID sont marquées pour la redécision de leur personne."""
        conn = sa_sync_conn
        owner, other = _persons(conn)
        by_orcid = _contributions(conn, 2, owner, "orcid")
        _contribution(conn, owner, "manual")
        _contribution(conn, owner, "idref")
        _contributions(conn, 5, other, "name")

        assert _arbitrate(conn)["transferred"] == 1

        assert _orcid_owner(conn) == other
        assert queued(conn, Queue.CONTRIBUTION_RESOLUTION) == set(by_orcid)
        assert _person_of(conn, by_orcid[0]) == (owner, "orcid")

    def test_les_contributions_rattachees_par_l_identifiant_votent(self, sa_sync_conn):
        """Trois contributions du titulaire rattachées par l'ORCID contre une contribution de l'autre personne rattachée par le nom : le titulaire garde l'ORCID. Un rattachement par identifiant suppose que le nom corrobore la personne."""
        conn = sa_sync_conn
        owner, other = _persons(conn)
        _contributions(conn, 3, owner, "orcid")
        _contribution(conn, other, "name")

        assert _arbitrate(conn)["transferred"] == 0

        assert _orcid_owner(conn) == owner

    def test_la_majorite_du_titulaire_garde_l_identifiant(self, sa_sync_conn):
        conn = sa_sync_conn
        owner, other = _persons(conn)
        _contributions(conn, 2, owner, "name")
        by_orcid = _contribution(conn, owner, "orcid")
        _contribution(conn, other, "name")

        assert _arbitrate(conn)["transferred"] == 0

        assert _orcid_owner(conn) == owner
        assert _person_of(conn, by_orcid) == (owner, "orcid")

    def test_un_orcid_d_une_source_non_fiable_ne_vote_pas(self, sa_sync_conn):
        conn = sa_sync_conn
        owner, other = _persons(conn)
        _contributions(conn, 3, other, "name", source="wos")

        assert _arbitrate(conn)["transferred"] == 0

        assert _orcid_owner(conn) == owner


def test_une_contribution_rattachee_par_un_identifiant_mal_place_est_marquee(sa_sync_conn, caplog):
    """Quatre contributions sources « jean martin » et trois « pierre dupont » contiennent l'ORCID : il est mal placé chez « pierre dupont ». La contribution de « pierre dupont » rattachée par l'ORCID est marquée pour la redécision de sa personne ; les contributions manuelle et rattachée par le nom restent en l'état."""
    conn = sa_sync_conn
    martin = insert_person(conn, "Martin", first_name="Jean")
    dupont = insert_person(conn, "Dupont", first_name="Pierre")
    _contributions(conn, 4, martin, "name")
    by_orcid = _contribution(conn, dupont, "orcid", name="pierre dupont")
    _contribution(conn, dupont, "manual", name="pierre dupont")
    _contribution(conn, dupont, "name", name="pierre dupont")

    with caplog.at_level(logging.INFO):
        result = _arbitrate(conn)

    assert (result["neutralized"], result["marked_contributions"]) == (3, 1)
    assert (
        "  ├─ Identifiants portés sous le nom d'une autre personne : 3 identifiants neutralisés"
        in caplog.messages
    )
    assert queued(conn, Queue.CONTRIBUTION_RESOLUTION) == {by_orcid}
    assert _person_of(conn, by_orcid) == (dupont, "orcid")


def test_sans_conflit_chaque_sous_etape_dit_rien_a_faire(sa_sync_conn, caplog):
    with caplog.at_level(logging.INFO):
        _arbitrate(sa_sync_conn)

    assert (
        "  ├─ Identifiants portés sous le nom d'une autre personne : rien à faire"
        in caplog.messages
    )
    assert "  └─ Conflits d'attribution : rien à faire" in caplog.messages
