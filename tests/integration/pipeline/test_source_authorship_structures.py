"""Branches `ror` et `hal_structure` de la vue `source_authorship_structures`."""

from sqlalchemy import text

from domain.structures.hal_structures import parse_hal_structure
from pipeline.transformation.structures.hal_structures import HalStructuresQueries
from pipeline.transformation.structures.perimeter import refresh_perimeter_structures
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.config import set_config
from tests.integration.helpers.sources import insert_signature, insert_source_publication
from tests.integration.helpers.structures import (
    insert_persons_perimeter,
    insert_structure,
    insert_tutelle,
)

_UNIV_ROR, _LAB_ROR = "01a8ajp46", "03vgfxd91"


def _hal(docid: int, *, parents=(), aliases=(), ror=None):
    structure = parse_hal_structure(
        {
            "docid": str(docid),
            "name_s": f"S{docid}",
            "type_s": "laboratory",
            "valid_s": "VALID",
            "parentDocid_i": [str(p) for p in parents],
            "aliasDocid_i": list(aliases),
            "ror_s": [f"https://ror.org/{ror}"] if ror else [],
        }
    )
    assert structure is not None
    return structure


def _perimeter(conn) -> tuple[int, int]:
    """Université et laboratoire du périmètre, avec leur ROR ; référentiel HAL : équipe 3 → laboratoire 2 (alias 9) → université 1."""
    univ = insert_persons_perimeter(conn)
    lab = insert_structure(conn, "LAB")
    insert_tutelle(conn, univ, child_id=lab)
    for structure_id, ror in ((univ, _UNIV_ROR), (lab, _LAB_ROR)):
        conn.execute(
            text("UPDATE structures SET ror_id = :r WHERE id = :i"), {"r": ror, "i": structure_id}
        )
    set_config(conn, "perimeter_extraction", "uca")
    refresh_perimeter_structures(conn)
    HalStructuresQueries(conn).save(
        [
            _hal(1, ror=_UNIV_ROR),
            _hal(2, parents=[1], aliases=[9], ror=_LAB_ROR),
            _hal(3, parents=[2]),
        ],
        {9: 2},
    )
    return univ, lab


def _signature(
    conn, record: int, position: int, *, hal_structures=(), ror=None, address_id=None
) -> int:
    signature = insert_signature(conn, record, author_position=position)
    for hal_structure_id in hal_structures:
        conn.execute(
            text("INSERT INTO source_authorship_hal_structures VALUES (:s, :h)"),
            {"s": signature, "h": hal_structure_id},
        )
    if ror:
        conn.execute(
            text(
                "INSERT INTO source_authorship_rors (source_authorship_id, ror_id, address_id) VALUES (:s, :r, :a)"
            ),
            {"s": signature, "r": ror, "a": address_id},
        )
    return signature


def _reached(conn) -> set[tuple[int, int, str]]:
    conn.execute(text("REFRESH MATERIALIZED VIEW source_authorship_structures"))
    return {
        (r.source_authorship_id, r.structure_id, r.evidence)
        for r in conn.execute(
            text(
                "SELECT source_authorship_id, structure_id, evidence::text FROM source_authorship_structures"
            )
        )
    }


def test_structure_hal_remonte_jusqu_a_la_premiere_correspondance(sa_sync_conn):
    _, lab = _perimeter(sa_sync_conn)
    # L'équipe 3, sans correspondance, remonte au laboratoire ; l'université, tutelle de l'équipe, est écartée.
    record = insert_source_publication(sa_sync_conn)
    equipe = _signature(sa_sync_conn, record, 0, hal_structures=[3, 1])
    # L'alias 9 se ramène au laboratoire 2.
    alias = _signature(sa_sync_conn, record, 1, hal_structures=[9])

    assert _reached(sa_sync_conn) == {
        (equipe, lab, "hal_structure"),
        (alias, lab, "hal_structure"),
    }


def test_ror_de_la_signature_et_ror_d_une_adresse_hors_perimetre(sa_sync_conn):
    _, lab = _perimeter(sa_sync_conn)
    record = insert_source_publication(sa_sync_conn)
    seul = _signature(sa_sync_conn, record, 0, ror=_LAB_ROR)
    hors = _signature(
        sa_sync_conn, record, 1, ror=_LAB_ROR, address_id=insert_address(sa_sync_conn, "Ailleurs")
    )

    reached = _reached(sa_sync_conn)

    assert (seul, lab, "ror") in reached
    assert not any(signature == hors for signature, _, _ in reached)
