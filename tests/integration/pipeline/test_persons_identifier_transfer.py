"""Arbitrage des identifiants de personne au niveau des contributions : redécision des contributions rattachées par un identifiant neutralisé `misplaced`."""

import logging

from sqlalchemy import text

from infrastructure.db.queues import Queue
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.persons import insert_person
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
    return arbitrate_identifier_conflicts(conn, _LOG)


def _person_of(conn, contribution):
    return tuple(
        conn.execute(
            text("SELECT person_id, resolution_mode FROM contributions WHERE id = :g"),
            {"g": contribution},
        ).one()
    )


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
        "  └─ Identifiants portés sous le nom d'une autre personne : 3 identifiants neutralisés"
        in caplog.messages
    )
    assert queued(conn, Queue.CONTRIBUTION_RESOLUTION) == {by_orcid}
    assert _person_of(conn, by_orcid) == (dupont, "orcid")


def test_sans_identifiant_mal_place_la_ligne_dit_rien_a_faire(sa_sync_conn, caplog):
    with caplog.at_level(logging.INFO):
        _arbitrate(sa_sync_conn)

    assert (
        "  └─ Identifiants portés sous le nom d'une autre personne : rien à faire"
        in caplog.messages
    )
