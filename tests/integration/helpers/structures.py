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

from pipeline.structures.perimeter import refresh_perimeter_structures
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.config import set_config
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
    row_id: int | None = None,
    name: str | None = None,
    acronym: str | None = None,
    structure_type: str = "labo",
    hal_collection: str | None = None,
    api_ids: dict[str, object] | None = None,
) -> int:
    """Insère une structure et renvoie son `id`. `row_id` fixe l'`id`. Le nom vaut le code par défaut."""
    return insert_row(
        conn,
        "structures",
        {
            "id": row_id,
            "code": code,
            "name": name if name is not None else code,
            "acronym": acronym,
            "structure_type": structure_type,
            "hal_collection": hal_collection,
            "api_ids": json.dumps(api_ids) if api_ids else None,
        },
        {"structure_type": "structure_type", "api_ids": "jsonb"},
    )


def insert_structure_name_form(
    conn: Connection,
    structure_id: int,
    *,
    form_text: str,
    is_word_boundary: bool | None = None,
    requires_context_of: list[int] | None = None,
) -> int:
    """Insère une forme de nom de la structure `structure_id` et renvoie son `id`. Par défaut, une forme de 6 caractères au plus est en mots entiers, comme l'exige la table."""
    return insert_row(
        conn,
        "structure_name_forms",
        {
            "structure_id": structure_id,
            "form_text": form_text,
            "is_word_boundary": (
                is_word_boundary if is_word_boundary is not None else len(form_text) <= 6
            ),
            "requires_context_of": requires_context_of,
        },
        {"requires_context_of": "integer[]"},
    )


def insert_tutelle(conn: Connection, parent_id: int, *, child_id: int) -> int:
    """Pose la tutelle de `parent_id` sur `child_id` et renvoie son `id`."""
    return insert_row(conn, "structure_tutelles", {"parent_id": parent_id, "child_id": child_id})


def insert_perimeter(
    conn: Connection,
    code: str,
    *,
    root_structure_ids: list[int] | None = None,
    name: str | None = None,
    materialize: bool = False,
    replace: bool = False,
) -> int:
    """Insère un périmètre et renvoie son `id`. Le nom vaut le code par défaut, les racines une liste vide. `replace` remplace les racines d'un périmètre de même code. `materialize` calcule sa clôture dans `perimeter_structures`."""
    conflict = (
        " ON CONFLICT (code) DO UPDATE SET root_structure_ids = EXCLUDED.root_structure_ids"
        if replace
        else ""
    )
    perimeter_id = conn.execute(
        text(
            "INSERT INTO perimeters (code, name, root_structure_ids) "
            f"VALUES (:code, :name, CAST(:roots AS integer[])){conflict} RETURNING id"
        ),
        {
            "code": code,
            "name": name if name is not None else code,
            "roots": root_structure_ids or [],
        },
    ).scalar_one()
    if materialize:
        refresh_perimeter_structures(conn)
    return perimeter_id


def add_to_perimeter(conn: Connection, structure_id: int, *, code: str, name: str) -> int:
    """Rattache `structure_id` au périmètre `code`, créé sous le nom `name` s'il est absent, et renvoie l'`id` du périmètre."""
    perimeter_id = conn.execute(
        text(
            "INSERT INTO perimeters (code, name) VALUES (:code, :name) "
            "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id"
        ),
        {"code": code, "name": name},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO perimeter_structures (perimeter_id, structure_id) "
            "VALUES (:p, :s) ON CONFLICT DO NOTHING"
        ),
        {"p": perimeter_id, "s": structure_id},
    )
    return perimeter_id


def insert_persons_perimeter(conn: Connection, code: str = "uca", *, extra_root_ids=()) -> int:
    """Pose l'université de code `code` en majuscules, racine du périmètre `code` avec `extra_root_ids`, et désigne ce périmètre comme celui des personnes. Renvoie l'`id` de l'université."""
    root = insert_structure(conn, code.upper(), structure_type="universite")
    insert_perimeter(conn, code, root_structure_ids=[root, *extra_root_ids], name=code.upper())
    set_config(conn, "perimeter_persons", code)
    return root


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
    (via une signature qui atteste l'authorship + appartenance au périmètre d'affiliation),
    puis rafraîchit `source_authorship_structures` et `authorship_structures`.

    La signature atteste l'authorship par sa publication et sa personne."""
    publication_id, person_id = conn.execute(
        text("SELECT publication_id, person_id FROM authorships WHERE id = :id"),
        {"id": authorship_id},
    ).one()
    sp_id = insert_source_publication(
        conn, source_id=f"as-test-{next(_seq)}", pub_year=2024, publication_id=publication_id
    )
    sa_id = insert_signature(conn, sp_id, person_id=person_id)
    add_source_authorship_structure(conn, sa_id, structure_id)


def add_source_authorship_structure(conn, sa_id: int, structure_id: int) -> None:
    """Lie la signature `sa_id` à `structure_id` par une adresse, rattache la structure au périmètre d'extraction, puis rafraîchit les matviews de structures."""
    raw_text = f"as-test-addr-{next(_seq)}"
    addr_id = insert_address(conn, raw_text, normalized_text=raw_text)
    insert_signature_address(conn, sa_id, address_id=addr_id)
    insert_address_structure(conn, addr_id, structure_id=structure_id)
    # La matview SAS filtre sur le périmètre d'extraction : garantir qu'un
    # périmètre d'extraction existe (config + ligne perimeters) et y rattacher
    # la structure pour que le lien apparaisse. Coopère avec les tests qui
    # configurent déjà `perimeter_extraction`.
    set_config(conn, "perimeter_extraction", "alliance_uca", replace=False)
    code = conn.execute(
        text("SELECT value #>> '{}' FROM config WHERE key = 'perimeter_extraction'")
    ).scalar_one()
    add_to_perimeter(conn, structure_id, code=code, name="test extraction perimeter")
    refresh_structure_matviews(conn)
