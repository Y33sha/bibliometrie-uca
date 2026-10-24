"""Idempotence : phase personnes (arbitrage des identifiants, rattachement des groupes, formes de nom, purge)."""

import logging

from sqlalchemy import text

from application.services.persons.core import create_person
from infrastructure.repositories import person_repository
from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.transformation.persons.groups import resolve_groups
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from pipeline.transformation.persons.populate_person_name_forms import populate
from pipeline.transformation.persons.purge import purge
from tests.integration.helpers.groups import group_ungrouped, recompose_group_attributes
from tests.integration.helpers.persons import insert_person_identifier
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_EVE_ORCID = "0000-0001-9999-0001"


def _setup(conn) -> dict[str, int]:
    """Deux publications HAL du périmètre. Eve Leroy (compte HAL 900001, ORCID) signe les deux, Frank Moreau (compte HAL 900002) la première, Grace Petit (sans identifiant) la seconde. Les trois personnes existent, Eve et Frank avec leur compte HAL. Rend les personnes par prénom."""
    repo = person_repository(conn)
    persons = {
        "eve": create_person("Leroy", "Eve", repo=repo),
        "frank": create_person("Moreau", "Frank", repo=repo),
        "grace": create_person("Petit", "Grace", repo=repo),
    }
    for name, account in (("eve", "900001"), ("frank", "900002")):
        insert_person_identifier(
            conn, persons[name], id_type="hal_person_id", id_value=account, status="confirmed"
        )

    eve = ("Eve Leroy", {"orcid": _EVE_ORCID, "hal_person_id": 900001})
    frank = ("Frank Moreau", {"hal_person_id": 900002})
    grace = ("Grace Petit", None)
    for index, authors in enumerate(((eve, frank), (eve, grace))):
        publication = insert_publication(conn, f"Test {index}")
        source_record = insert_source_record(conn, publication, source_id=f"hal-9000000{index}")
        for position, (raw, identifiers) in enumerate(authors):
            insert_source_contribution(
                conn,
                source_record,
                author_position=position,
                raw_author_name=raw,
                author_name_normalized=raw.lower(),
                identifiers=identifiers,
                in_perimeter=True,
            )
    group_ungrouped(conn)
    recompose_group_attributes(conn)
    return persons


def _run(conn) -> None:
    arbitrate_identifier_conflicts(conn, logging.getLogger("test"), repo=PgPersonRepository(conn))
    resolve_groups(conn)
    populate(conn)
    purge(conn)


def _state(conn) -> dict[str, object]:
    counts: dict[str, object] = {
        table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in ("persons", "person_name_forms", "person_identifiers")
    }
    counts["groups"] = sorted(
        tuple(r)
        for r in conn.execute(
            text("SELECT id, person_id, resolution_mode::text FROM source_contribution_groups")
        )
    )
    return counts


def test_deux_executions_donnent_le_meme_etat(sa_sync_conn):
    _setup(sa_sync_conn)

    _run(sa_sync_conn)
    first = _state(sa_sync_conn)
    _run(sa_sync_conn)

    assert _state(sa_sync_conn) == first


def test_les_groupes_d_un_meme_compte_hal_vont_a_la_meme_personne(sa_sync_conn):
    persons = _setup(sa_sync_conn)

    _run(sa_sync_conn)

    attached = sa_sync_conn.execute(
        text("SELECT person_id, count(*) FROM source_contribution_groups GROUP BY person_id")
    ).all()
    assert dict(attached) == {persons["eve"]: 2, persons["frank"]: 1, persons["grace"]: 1}


def test_l_orcid_des_membres_est_attribue(sa_sync_conn):
    persons = _setup(sa_sync_conn)

    _run(sa_sync_conn)

    owner = sa_sync_conn.execute(
        text("SELECT person_id FROM person_identifiers WHERE id_type = 'orcid' AND id_value = :v"),
        {"v": _EVE_ORCID},
    ).scalar_one()
    assert owner == persons["eve"]
