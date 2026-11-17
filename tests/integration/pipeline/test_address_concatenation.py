"""Tâche `affiliations.detect_concatenated_addresses` : détection des adresses concaténées parmi les adresses non examinées."""

import logging

from sqlalchemy import text

from pipeline.transformation.structures.address_concatenation import (
    detect_concatenated_addresses,
)
from tests.integration.helpers.addresses import insert_address

LOGGER = logging.getLogger(__name__)

_CONCATENATED = "Neurology Department, Clermont-Ferrand (E.D., B.D.); CHU of Lille (C.M.)"
_SINGLE = "Grenoble University Hospital, France (P.D.)"


def _flags(conn) -> dict[str, bool | None]:
    rows = conn.execute(text("SELECT raw_text, is_concatenated FROM addresses")).all()
    return {r.raw_text: r.is_concatenated for r in rows}


def test_les_adresses_non_examinees_sont_examinees(sa_sync_conn):
    for raw_text in (_CONCATENATED, _SINGLE, "Institut Pascal, Aubière, France"):
        insert_address(sa_sync_conn, raw_text)

    metrics = detect_concatenated_addresses(sa_sync_conn, LOGGER, chunk_size=2)

    assert metrics.updated == 3
    assert _flags(sa_sync_conn) == {
        _CONCATENATED: True,
        _SINGLE: False,
        "Institut Pascal, Aubière, France": False,
    }


def test_une_adresse_examinee_reste_en_place(sa_sync_conn):
    address_id = insert_address(sa_sync_conn, _CONCATENATED)
    sa_sync_conn.execute(
        text("UPDATE addresses SET is_concatenated = false WHERE id = :id"), {"id": address_id}
    )

    metrics = detect_concatenated_addresses(sa_sync_conn, LOGGER)

    assert metrics.updated == 0
    assert _flags(sa_sync_conn) == {_CONCATENATED: False}
