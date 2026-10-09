"""Semis de structures et de périmètres, et liens authorship ↔ structure, sur la connexion SQLAlchemy (`sa_sync_conn`).

`authorship_structures` et `source_authorship_structures` sont des
MATERIALIZED VIEW (migrations a2c6e4f8b1d7, e8f1a3c5d7b9) — les tests ne peuvent
plus les `INSERT` directement. Ce helper sème la chaîne source minimale
(source_authorship → adresse → address_structures, structure rattachée au
périmètre d'affiliation) puis rafraîchit les deux matviews (transactionnel :
rollback avec le test).
"""

import itertools
import json

from sqlalchemy import Connection, text

from infrastructure.pipeline.perimeter import refresh_perimeter_structures
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.rows import insert_row
from tests.integration.helpers.sources import (
    insert_signature,
    insert_signature_address,
    insert_source_publication,
)

_seq = itertools.count(1)


def insert_structure(
    conn: Connection,
    code: str = "X",
    *,
    name: str | None = None,
    structure_type: str = "labo",
    hal_collection: str | None = None,
    api_ids: dict[str, object] | None = None,
) -> int:
    """Insère une structure et renvoie son `id`. Le nom vaut le code par défaut."""
    return insert_row(
        conn,
        "structures",
        {
            "code": code,
            "name": name if name is not None else code,
            "structure_type": structure_type,
            "hal_collection": hal_collection,
            "api_ids": json.dumps(api_ids) if api_ids else None,
        },
        {"structure_type": "structure_type", "api_ids": "jsonb"},
    )


def insert_perimeter(
    conn: Connection,
    code: str,
    *,
    root_structure_ids: list[int] | None = None,
    name: str | None = None,
    materialize: bool = False,
) -> int:
    """Insère un périmètre et renvoie son `id`. Le nom vaut le code par défaut, les racines une liste vide. `materialize` calcule sa clôture dans `perimeter_structures`."""
    perimeter_id = insert_row(
        conn,
        "perimeters",
        {
            "code": code,
            "name": name if name is not None else code,
            "root_structure_ids": root_structure_ids or [],
        },
        {"root_structure_ids": "integer[]"},
    )
    if materialize:
        refresh_perimeter_structures(conn)
    return perimeter_id


def refresh_structure_matviews(conn) -> None:
    """Rafraîchit `source_authorship_structures` → `authorship_structures` →
    `publication_structures` (chaîne matview-sur-matview, ordre imposé).
    Non-concurrent = transactionnel, donc compatible avec l'isolation par rollback
    des tests. En prod ces matviews sont maintenues par le pipeline ; les tests les
    rafraîchissent explicitement."""
    conn.execute(text("REFRESH MATERIALIZED VIEW source_authorship_structures"))
    conn.execute(text("REFRESH MATERIALIZED VIEW authorship_structures"))
    conn.execute(text("REFRESH MATERIALIZED VIEW publication_structures"))


def add_authorship_structure(conn, authorship_id: int, structure_id: int) -> None:
    """Lie `authorship_id` à `structure_id` dans la matview `authorship_structures`
    (via une chaîne source minimale + appartenance au périmètre d'affiliation),
    puis rafraîchit `source_authorship_structures` et `authorship_structures`."""
    sp_id = insert_source_publication(conn, source_id=f"as-test-{next(_seq)}", pub_year=2024)
    sa_id = insert_signature(conn, sp_id, authorship_id=authorship_id)
    add_source_authorship_structure(conn, sa_id, structure_id)


def add_source_authorship_structure(conn, sa_id: int, structure_id: int) -> None:
    """Lie la signature `sa_id` à `structure_id` par une adresse, rattache la structure au périmètre d'extraction, puis rafraîchit les matviews de structures."""
    raw_text = f"as-test-addr-{next(_seq)}"
    addr_id = insert_address(conn, raw_text, normalized_text=raw_text)
    insert_signature_address(conn, sa_id, address_id=addr_id)
    conn.execute(
        text(
            "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
            "VALUES (:a, :s, NULL)"
        ),
        {"a": addr_id, "s": structure_id},
    )
    # La matview SAS filtre sur le périmètre d'extraction : garantir qu'un
    # périmètre d'extraction existe (config + ligne perimeters) et y rattacher
    # la structure pour que le lien apparaisse. Coopère avec les tests qui
    # configurent déjà `perimeter_extraction` (ON CONFLICT DO NOTHING).
    conn.execute(
        text(
            "INSERT INTO config (key, value) VALUES ('perimeter_extraction', '\"alliance_uca\"') "
            "ON CONFLICT (key) DO NOTHING"
        )
    )
    perim_id = conn.execute(
        text("""
            INSERT INTO perimeters (code, name)
            SELECT value #>> '{}', 'test extraction perimeter'
            FROM config WHERE key = 'perimeter_extraction'
            ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code
            RETURNING id
        """)
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO perimeter_structures (perimeter_id, structure_id) "
            "VALUES (:p, :s) ON CONFLICT DO NOTHING"
        ),
        {"p": perim_id, "s": structure_id},
    )
    refresh_structure_matviews(conn)
