"""Écriture du référentiel des structures HAL, et structures à charger."""

from dataclasses import replace

from sqlalchemy import text

from domain.structures.hal_structures import HalStructureStatus, parse_hal_structure
from infrastructure.db.queues import Queue
from pipeline.transformation.structures.hal_structures import HalStructureStore
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _structure(docid: int, *, parents=(), aliases=()):
    structure = parse_hal_structure(
        {
            "docid": str(docid),
            "name_s": f"S{docid}",
            "type_s": "laboratory",
            "valid_s": HalStructureStatus.VALID.value,
            "parentDocid_i": [str(p) for p in parents],
            "aliasDocid_i": list(aliases),
        }
    )
    assert structure is not None
    return structure


def _relations(conn):
    return {
        tuple(r)
        for r in conn.execute(text("SELECT parent_id, child_id FROM hal_structure_relations"))
    }


def test_relations_reconstruites_depuis_parent_ids(sa_sync_conn):
    store = HalStructureStore(sa_sync_conn)
    # 3 cite son parent par l'alias 9 de la structure 2 ; 5 est hors du référentiel.
    store.save([_structure(2, aliases=[9]), _structure(3, parents=[9, 5])], {9: 2})
    store.rebuild_relations()

    assert _relations(sa_sync_conn) == {(2, 3)}

    # Les relations de 3 sont celles de sa dernière lecture.
    store.save([_structure(3)], {})
    store.rebuild_relations()
    assert _relations(sa_sync_conn) == set()


def test_ids_to_fetch_ecarte_les_structures_et_alias_connus(sa_sync_conn):
    store = HalStructureStore(sa_sync_conn)
    store.save([_structure(2, aliases=[9])], {9: 2})
    record = insert_source_record(sa_sync_conn, source="hal", source_id="hal-1")
    for hal_structure_id in (2, 9, 4):
        source_contribution = insert_source_contribution(
            sa_sync_conn, record, source="hal", author_position=hal_structure_id
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_contribution_hal_structures (source_contribution_id, hal_structure_id)"
                " VALUES (:s, :h)"
            ),
            {"s": source_contribution, "h": hal_structure_id},
        )

    assert store.ids_to_fetch(refresh_stale=False) == {4}
    sa_sync_conn.execute(text("UPDATE hal_structures SET fetched_at = now() - interval '60 days'"))
    assert store.ids_to_fetch(refresh_stale=True) == {2, 4}


def test_un_changement_de_pays_marque_les_contributions_sources_de_la_structure_et_de_ses_alias(
    sa_sync_conn,
):
    store = HalStructureStore(sa_sync_conn)
    store.save([_structure(2, aliases=[9]), _structure(3)], {9: 2})
    record = insert_source_record(sa_sync_conn, source="hal", source_id="hal-1")
    cited = {}
    for position, hal_structure_id in enumerate((2, 9, 3)):
        cited[hal_structure_id] = insert_source_contribution(
            sa_sync_conn, record, source="hal", author_position=position
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_contribution_hal_structures (source_contribution_id, hal_structure_id)"
                " VALUES (:s, :h)"
            ),
            {"s": cited[hal_structure_id], "h": hal_structure_id},
        )
    clear(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES)

    store.save([replace(_structure(2, aliases=[9]), country_code="fr"), _structure(3)], {9: 2})

    assert queued(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES) == {cited[2], cited[9]}


def test_ids_to_fetch_reprend_les_parents_absents(sa_sync_conn):
    store = HalStructureStore(sa_sync_conn)
    store.save([_structure(3, parents=[2])], {})

    assert store.ids_to_fetch(refresh_stale=False) == {2}
