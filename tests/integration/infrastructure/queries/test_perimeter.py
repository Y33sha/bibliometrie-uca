"""Tests d'intégration de `refresh_perimeter_structures`.

Vérifie que la table matérialisée `perimeter_structures` reproduit la clôture
récursive des racines `perimeters.root_structure_ids`, et que le refresh est
idempotent.
"""

from sqlalchemy import text

from infrastructure.pipeline.perimeter import refresh_perimeter_structures


def _structure(conn, code: str, stype: str = "labo") -> int:
    return conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (:c, :c, CAST(:t AS structure_type)) RETURNING id"
        ),
        {"c": code, "t": stype},
    ).scalar_one()


def _tutelle(conn, parent_id: int, child_id: int) -> None:
    conn.execute(
        text("INSERT INTO structure_tutelles (parent_id, child_id) VALUES (:p, :c)"),
        {"p": parent_id, "c": child_id},
    )


def _perimeter(conn, code: str, roots: list[int]) -> int:
    return conn.execute(
        text(
            "INSERT INTO perimeters (code, name, root_structure_ids) "
            "VALUES (:c, :c, CAST(:ids AS integer[])) RETURNING id"
        ),
        {"c": code, "ids": roots},
    ).scalar_one()


def _closure(conn, perimeter_id: int) -> set[int]:
    rows = conn.execute(
        text("SELECT structure_id FROM perimeter_structures WHERE perimeter_id = :p"),
        {"p": perimeter_id},
    ).all()
    return {r.structure_id for r in rows}


def test_closure_descends_transitively(sa_sync_conn):
    conn = sa_sync_conn
    root = _structure(conn, "ps_test_root", "universite")
    child = _structure(conn, "ps_test_child")
    grandchild = _structure(conn, "ps_test_grandchild")
    unrelated = _structure(conn, "ps_test_unrelated")
    _tutelle(conn, root, child)
    _tutelle(conn, child, grandchild)
    perim = _perimeter(conn, "ps_test_perim", [root])

    refresh_perimeter_structures(conn)

    # Racine et descendants, transitivement ; pas la structure sans tutelle.
    closure = _closure(conn, perim)
    assert closure == {root, child, grandchild}
    assert unrelated not in closure


def test_refresh_idempotent(sa_sync_conn):
    conn = sa_sync_conn
    root = _structure(conn, "ps_test_root2", "universite")
    child = _structure(conn, "ps_test_child2")
    _tutelle(conn, root, child)
    perim = _perimeter(conn, "ps_test_perim2", [root])

    refresh_perimeter_structures(conn)
    first = _closure(conn, perim)
    refresh_perimeter_structures(conn)
    second = _closure(conn, perim)

    assert first == second == {root, child}
