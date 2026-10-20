"""Écriture du référentiel des structures HAL, et structures à charger."""

from dataclasses import replace

from sqlalchemy import text

from domain.structures.hal_structures import HalStructureStatus, parse_hal_structure
from pipeline.transformation.structures.hal_structures import HalStructuresQueries
from tests.integration.helpers.sources import insert_signature, insert_source_record


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
    queries = HalStructuresQueries(sa_sync_conn)
    # 3 cite son parent par l'alias 9 de la structure 2 ; 5 est hors du référentiel.
    queries.save([_structure(2, aliases=[9]), _structure(3, parents=[9, 5])], {9: 2})
    queries.rebuild_relations()

    assert _relations(sa_sync_conn) == {(2, 3)}

    # Les relations de 3 sont celles de sa dernière lecture.
    queries.save([_structure(3)], {})
    queries.rebuild_relations()
    assert _relations(sa_sync_conn) == set()


def test_ids_to_fetch_ecarte_les_structures_et_alias_connus(sa_sync_conn):
    queries = HalStructuresQueries(sa_sync_conn)
    queries.save([_structure(2, aliases=[9])], {9: 2})
    record = insert_source_record(sa_sync_conn, source="hal", source_id="hal-1")
    for hal_structure_id in (2, 9, 4):
        signature = insert_signature(
            sa_sync_conn, record, source="hal", author_position=hal_structure_id
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_contribution_hal_structures (source_contribution_id, hal_structure_id)"
                " VALUES (:s, :h)"
            ),
            {"s": signature, "h": hal_structure_id},
        )

    assert queries.ids_to_fetch(refresh_stale=False) == {4}
    sa_sync_conn.execute(text("UPDATE hal_structures SET fetched_at = now() - interval '60 days'"))
    assert queries.ids_to_fetch(refresh_stale=True) == {2, 4}


def test_un_changement_de_pays_marque_les_signatures_de_la_structure_et_de_ses_alias(
    sa_sync_conn,
):
    queries = HalStructuresQueries(sa_sync_conn)
    queries.save([_structure(2, aliases=[9]), _structure(3)], {9: 2})
    record = insert_source_record(sa_sync_conn, source="hal", source_id="hal-1")
    cited = {}
    for position, hal_structure_id in enumerate((2, 9, 3)):
        cited[hal_structure_id] = insert_signature(
            sa_sync_conn, record, source="hal", author_position=position
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_contribution_hal_structures (source_contribution_id, hal_structure_id)"
                " VALUES (:s, :h)"
            ),
            {"s": cited[hal_structure_id], "h": hal_structure_id},
        )
    sa_sync_conn.execute(text("UPDATE source_contributions SET countries_dirty = false"))

    queries.save([replace(_structure(2, aliases=[9]), country_code="fr"), _structure(3)], {9: 2})

    dirty = set(
        sa_sync_conn.execute(
            text("SELECT id FROM source_contributions WHERE countries_dirty")
        ).scalars()
    )
    assert dirty == {cited[2], cited[9]}


def test_ids_to_fetch_reprend_les_parents_absents(sa_sync_conn):
    queries = HalStructuresQueries(sa_sync_conn)
    queries.save([_structure(3, parents=[2])], {})

    assert queries.ids_to_fetch(refresh_stale=False) == {2}
