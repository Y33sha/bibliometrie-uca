"""Tâche `affiliations.classify_addresses` : origine du texte des adresses sans origine."""

import logging

from sqlalchemy import text

from domain.normalize import normalize_text
from pipeline.transformation.structures.address_origin import classify_addresses
from tests.integration.helpers.addresses import ensure_country, insert_address

LOGGER = logging.getLogger(__name__)


def _address(conn, raw_text: str) -> int:
    return insert_address(conn, raw_text, normalized_text=normalize_text(raw_text))


def _origins(conn) -> dict[str, str]:
    rows = conn.execute(text("SELECT raw_text, origin::text AS origin FROM addresses")).all()
    return {r.raw_text: r.origin for r in rows}


def _seed_referentials(conn) -> None:
    ensure_country(conn, "fr", "France")
    conn.execute(
        text("""
            INSERT INTO place_name_forms (iso_code, form_normalized, kind)
            VALUES ('fr', 'france', 'country') ON CONFLICT DO NOTHING;
            INSERT INTO hal_structures (hal_structure_id, name, structure_type, status)
            VALUES (990001, 'Laboratoire de test HAL', 'laboratory', 'VALID');
            INSERT INTO ror_organizations (ror_id, name, country_code, types, status)
            VALUES ('0test0001', 'Organisation de test ROR', 'fr', '{facility}', 'active');
        """)
    )


def test_les_adresses_sans_origine_sont_classees(sa_sync_conn):
    _seed_referentials(sa_sync_conn)
    for raw_text in (
        "IP - Institut Pascal (Campus des Cézeaux, 63178 Aubière - France)",
        "Laboratoire de test HAL",
        "ORGANISATION DE TEST ROR",
        "Institut Pascal, Aubière, France",
        "Department of Pediatrics University Hospital Rouen France",
        "Professeur",
    ):
        _address(sa_sync_conn, raw_text)

    metrics = classify_addresses(sa_sync_conn, LOGGER)

    assert metrics.updated == 6
    assert _origins(sa_sync_conn) == {
        "IP - Institut Pascal (Campus des Cézeaux, 63178 Aubière - France)": "hal_label",
        "Laboratoire de test HAL": "name_only",
        "ORGANISATION DE TEST ROR": "name_only",
        "Institut Pascal, Aubière, France": "raw",
        "Department of Pediatrics University Hospital Rouen France": "raw",
        "Professeur": "name_only",
    }


def test_une_origine_posee_reste_en_place(sa_sync_conn):
    _seed_referentials(sa_sync_conn)
    address_id = _address(sa_sync_conn, "Institut Pascal, Aubière, France")
    sa_sync_conn.execute(
        text("UPDATE addresses SET origin = 'name_only' WHERE id = :id"), {"id": address_id}
    )

    metrics = classify_addresses(sa_sync_conn, LOGGER)

    assert metrics.updated == 0
    assert _origins(sa_sync_conn) == {"Institut Pascal, Aubière, France": "name_only"}
