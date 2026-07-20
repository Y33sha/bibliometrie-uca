"""Tests d'intégration de `refresh_perimeter_structures`.

Vérifie que la table matérialisée `perimeter_structures` reproduit la clôture
récursive `est_tutelle_de` des racines `perimeters.root_structure_ids` (et seulement
elle : pas de descente `est_partenaire_de`), et que le refresh est idempotent.
"""

from sqlalchemy import text

from infrastructure.queries.perimeter import refresh_perimeter_structures


def _structure(conn, code: str, stype: str = "labo") -> int:
    return conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (:c, :c, CAST(:t AS structure_type)) RETURNING id"
        ),
        {"c": code, "t": stype},
    ).scalar_one()


def _relation(conn, parent_id: int, child_id: int, rtype: str) -> None:
    conn.execute(
        text(
            "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
            "VALUES (:p, :c, :t)"
        ),
        {"p": parent_id, "c": child_id, "t": rtype},
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


def test_closure_descends_tutelle_only(sa_sync_conn):
    conn = sa_sync_conn
    root = _structure(conn, "ps_test_root", "universite")
    child = _structure(conn, "ps_test_child")
    grandchild = _structure(conn, "ps_test_grandchild")
    partner = _structure(conn, "ps_test_partner", "ecole")
    unrelated = _structure(conn, "ps_test_unrelated")
    _relation(conn, root, child, "est_tutelle_de")
    _relation(conn, child, grandchild, "est_tutelle_de")
    _relation(conn, root, partner, "est_partenaire_de")
    perim = _perimeter(conn, "ps_test_perim", [root])

    refresh_perimeter_structures(conn)

    # Racine + descendants est_tutelle_de (transitivement), pas le partenaire ni l'isolée.
    closure = _closure(conn, perim)
    assert closure == {root, child, grandchild}
    assert partner not in closure
    assert unrelated not in closure


def test_refresh_idempotent(sa_sync_conn):
    conn = sa_sync_conn
    root = _structure(conn, "ps_test_root2", "universite")
    child = _structure(conn, "ps_test_child2")
    _relation(conn, root, child, "est_tutelle_de")
    perim = _perimeter(conn, "ps_test_perim2", [root])

    refresh_perimeter_structures(conn)
    first = _closure(conn, perim)
    refresh_perimeter_structures(conn)
    second = _closure(conn, perim)

    assert first == second == {root, child}
