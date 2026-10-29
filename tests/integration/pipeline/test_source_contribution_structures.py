"""Branches `ror`, `hal_structure` et thèse de la vue `source_contribution_structures`."""

import json
import logging

from sqlalchemy import text

from domain.structures.hal_structures import parse_hal_structure
from pipeline.transformation.structures.hal_structures import HalStructureStore
from pipeline.transformation.structures.idref_resolution import resolve_thesis_partners
from pipeline.transformation.structures.perimeter import refresh_perimeter_structures
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.config import set_config
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)
from tests.integration.helpers.structures import (
    insert_persons_perimeter,
    insert_structure,
    insert_structure_name_form,
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
    HalStructureStore(conn).save(
        [
            _hal(1, ror=_UNIV_ROR),
            _hal(2, parents=[1], aliases=[9], ror=_LAB_ROR),
            _hal(3, parents=[2]),
        ],
        {9: 2},
    )
    HalStructureStore(conn).rebuild_relations()
    return univ, lab


def _source_contribution(
    conn, record: int, position: int, *, hal_structures=(), ror=None, address_id=None
) -> int:
    source_contribution = insert_source_contribution(conn, record, author_position=position)
    for hal_structure_id in hal_structures:
        conn.execute(
            text("INSERT INTO source_contribution_hal_structures VALUES (:s, :h)"),
            {"s": source_contribution, "h": hal_structure_id},
        )
    if ror:
        conn.execute(
            text(
                "INSERT INTO source_contribution_rors (source_contribution_id, ror_id, address_id) VALUES (:s, :r, :a)"
            ),
            {"s": source_contribution, "r": ror, "a": address_id},
        )
    return source_contribution


def _reached(conn) -> set[tuple[int, int, str]]:
    conn.execute(text("REFRESH MATERIALIZED VIEW source_contribution_structures"))
    return {
        (r.source_contribution_id, r.structure_id, r.evidence)
        for r in conn.execute(
            text(
                "SELECT source_contribution_id, structure_id, evidence::text FROM source_contribution_structures"
            )
        )
    }


def test_structure_hal_remonte_jusqu_a_la_premiere_correspondance(sa_sync_conn):
    _, lab = _perimeter(sa_sync_conn)
    # L'équipe 3, sans correspondance, remonte au laboratoire ; l'université, tutelle de l'équipe, est écartée.
    record = insert_source_record(sa_sync_conn)
    equipe = _source_contribution(sa_sync_conn, record, 0, hal_structures=[3, 1])
    # L'alias 9 se ramène au laboratoire 2.
    alias = _source_contribution(sa_sync_conn, record, 1, hal_structures=[9])

    assert _reached(sa_sync_conn) == {
        (equipe, lab, "hal_structure"),
        (alias, lab, "hal_structure"),
    }


def test_ror_sans_adresse_seulement(sa_sync_conn):
    univ, lab = _perimeter(sa_sync_conn)
    record = insert_source_record(sa_sync_conn)
    seul = _source_contribution(sa_sync_conn, record, 0, ror=_LAB_ROR)
    hors = _source_contribution(
        sa_sync_conn, record, 1, ror=_LAB_ROR, address_id=insert_address(sa_sync_conn, "Ailleurs")
    )
    # L'adresse, résolue vers l'université, fait autorité : le ROR du laboratoire est écarté.
    univ_address = insert_address(sa_sync_conn, "Université")
    insert_address_structure(sa_sync_conn, univ_address, structure_id=univ)
    dans = _source_contribution(sa_sync_conn, record, 2, ror=_LAB_ROR, address_id=univ_address)
    insert_source_contribution_address(sa_sync_conn, dans, address_id=univ_address)

    reached = _reached(sa_sync_conn)

    assert (seul, lab, "ror") in reached
    assert not any(source_contribution == hors for source_contribution, _, _ in reached)
    assert {(s, structure, e) for s, structure, e in reached if s == dans} == {
        (dans, univ, "address")
    }


def test_structure_hal_rattachee_explicitement(sa_sync_conn):
    _, lab = _perimeter(sa_sync_conn)
    # Une fiche hors de la hiérarchie, sans ROR, rattachée au laboratoire par `structure_id`.
    HalStructureStore(sa_sync_conn).save([_hal(5)], {})
    sa_sync_conn.execute(
        text("UPDATE hal_structures SET structure_id = :lab WHERE hal_structure_id = 5"),
        {"lab": lab},
    )
    record = insert_source_record(sa_sync_conn)
    ancienne = _source_contribution(sa_sync_conn, record, 0, hal_structures=[5])

    assert _reached(sa_sync_conn) == {(ancienne, lab, "hal_structure")}


def test_structures_d_une_these(sa_sync_conn):
    """L'établissement de soutenance rattache toutes les contributions sources ; le laboratoire partenaire, reconnu par son PPN et son nom, le seul doctorant."""
    univ, lab = _perimeter(sa_sync_conn)
    sa_sync_conn.execute(
        text("UPDATE structures SET api_ids = CAST(:ids AS jsonb) WHERE id = :id"),
        {"ids": json.dumps({"theses": ["196200032"]}), "id": univ},
    )
    insert_structure_name_form(sa_sync_conn, lab, form_text="laboratoire de test")
    record = insert_source_record(sa_sync_conn, source="theses", source_id="2021CLFAC001")
    sa_sync_conn.execute(
        text(
            "UPDATE source_records SET source_extras = CAST(:source_extras AS jsonb) WHERE id = :id"
        ),
        {
            "source_extras": json.dumps(
                {
                    "etablissement_ppn": "196200032",
                    "partenaires": [{"nom": "Laboratoire de test", "ppn": "123456789"}],
                }
            ),
            "id": record,
        },
    )
    doctorant = insert_source_contribution(
        sa_sync_conn, record, source="theses", author_position=0, roles=["author"]
    )
    jury = insert_source_contribution(
        sa_sync_conn, record, source="theses", author_position=None, roles=["jury_member"]
    )

    resolve_thesis_partners(sa_sync_conn, logging.getLogger("test"))

    assert _reached(sa_sync_conn) == {
        (doctorant, univ, "thesis_institution"),
        (jury, univ, "thesis_institution"),
        (doctorant, lab, "thesis_partner"),
    }
