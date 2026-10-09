"""Résolution des périmètres depuis `config` : une clé absente vaut périmètre vide, et le périmètre des personnes se rabat sur celui d'extraction."""

import json

from sqlalchemy import text

from infrastructure.read_models.perimeters import (
    get_extraction_structure_ids,
    get_persons_perimeter_name,
    get_persons_perimeter_root_ids,
    get_persons_structure_ids,
)
from tests.integration.helpers.structures import insert_perimeter, insert_structure


def _clear_perimeter_config(conn) -> None:
    conn.execute(
        text("DELETE FROM config WHERE key IN ('perimeter_extraction', 'perimeter_persons')")
    )


def _set_config(conn, key: str, value: str) -> None:
    conn.execute(text("DELETE FROM config WHERE key = :k"), {"k": key})
    conn.execute(
        text("INSERT INTO config (key, value) VALUES (:k, CAST(:v AS jsonb))"),
        {"k": key, "v": json.dumps(value)},
    )


def _perimeter(conn, code: str, name: str) -> int:
    """Crée un périmètre à une racine, matérialise sa clôture et rend l'identifiant de la racine."""
    root = insert_structure(conn, f"{code}_racine", structure_type="universite")
    insert_perimeter(conn, code, root_structure_ids=[root], name=name, materialize=True)
    return root


def test_absent_keys_give_empty_perimeters(sa_sync_conn):
    conn = sa_sync_conn
    _clear_perimeter_config(conn)

    assert get_extraction_structure_ids(conn) == set()
    assert get_persons_structure_ids(conn) == set()
    assert get_persons_perimeter_root_ids(conn) == []
    assert get_persons_perimeter_name(conn) == ""


def test_persons_perimeter_falls_back_to_extraction(sa_sync_conn):
    conn = sa_sync_conn
    _clear_perimeter_config(conn)
    root = _perimeter(conn, "res_extraction", "Extraction")
    _set_config(conn, "perimeter_extraction", "res_extraction")

    assert get_persons_structure_ids(conn) == {root}
    assert get_persons_perimeter_root_ids(conn) == [root]
    assert get_persons_perimeter_name(conn) == "Extraction"


def test_configured_persons_perimeter_prevails(sa_sync_conn):
    conn = sa_sync_conn
    _clear_perimeter_config(conn)
    _perimeter(conn, "res_extraction", "Extraction")
    persons_root = _perimeter(conn, "res_personnes", "Personnes")
    _set_config(conn, "perimeter_extraction", "res_extraction")
    _set_config(conn, "perimeter_persons", "res_personnes")

    assert get_persons_structure_ids(conn) == {persons_root}
    assert get_persons_perimeter_name(conn) == "Personnes"
