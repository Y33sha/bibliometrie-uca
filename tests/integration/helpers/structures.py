"""Semis de structures et de périmètres, et liens contribution ↔ structure, sur la connexion SQLAlchemy (`sa_sync_conn`).

`contribution_structures` et `source_contribution_structures` sont des
MATERIALIZED VIEW (migrations a2c6e4f8b1d7, e8f1a3c5d7b9) — les tests ne peuvent
plus les `INSERT` directement. Ce helper sème la chaîne source minimale
(source_contribution → adresse → address_structures, structure rattachée au
périmètre d'affiliation) puis rafraîchit les deux matviews (transactionnel :
rollback avec le test).
"""

import itertools
import json

from sqlalchemy import Connection, text

from pipeline.transformation.structures.perimeter import refresh_perimeter_structures
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.config import set_config
from tests.integration.helpers.rows import insert_row
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
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
    return insert_row(conn, "structure_parents", {"parent_id": parent_id, "child_id": child_id})


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


def insert_persons_perimeter(
    conn: Connection, code: str = "uca", *, extra_root_ids=(), materialize: bool = False
) -> int:
    """Pose l'université de code `code` en majuscules, racine du périmètre `code` avec `extra_root_ids`, et désigne ce périmètre comme celui des personnes. Renvoie l'`id` de l'université. `materialize` calcule la clôture du périmètre."""
    root = insert_structure(conn, code.upper(), structure_type="universite")
    insert_perimeter(
        conn,
        code,
        root_structure_ids=[root, *extra_root_ids],
        name=code.upper(),
        materialize=materialize,
    )
    set_config(conn, "perimeter_persons", code)
    return root


def refresh_structure_matviews(conn) -> None:
    """Rafraîchit les vues des structures dans l'ordre de leurs dépendances : `source_contribution_structures`, puis `contribution_structures`, puis `publication_structures`.

    Le rafraîchissement sans `CONCURRENTLY` est transactionnel, donc annulé avec le test. Le pipeline maintient ces vues ; les tests les rafraîchissent eux-mêmes."""
    conn.execute(text("REFRESH MATERIALIZED VIEW source_contribution_structures"))
    conn.execute(text("REFRESH MATERIALIZED VIEW contribution_structures"))
    conn.execute(text("REFRESH MATERIALIZED VIEW publication_structures"))


def add_contribution_structure(conn, contribution_id: int, structure_id: int) -> None:
    """Lie la contribution `contribution_id` à `structure_id`, par une contribution source de sa publication et de sa personne, alignée dans la contribution, qui atteint la structure, puis rafraîchit les vues des structures."""
    publication_id, person_id = conn.execute(
        text("SELECT publication_id, person_id FROM contributions WHERE id = :id"),
        {"id": contribution_id},
    ).one()
    source_record_id = insert_source_record(
        conn,
        source_id=f"as-test-{next(_seq)}",
        publication_year=2024,
        publication_id=publication_id,
    )
    source_contribution_id = insert_source_contribution(conn, source_record_id)
    conn.execute(
        text("""
            INSERT INTO aligned_source_contributions
                (source_contribution_id, contribution_id, source_record_id, method)
            SELECT :sc, g.id, :sr, 'reference'
            FROM contributions g
            WHERE g.publication_id = :p AND g.person_id = :person
        """),
        {
            "sc": source_contribution_id,
            "sr": source_record_id,
            "p": publication_id,
            "person": person_id,
        },
    )
    add_source_contribution_structure(conn, source_contribution_id, structure_id)


def add_source_contribution_ror(conn, source_contribution_id: int, structure_id: int) -> None:
    """Lie la contribution source `source_contribution_id` à `structure_id` par un ROR propre à la contribution source (indice `ror`), en donnant un ROR à la structure qui n'en a pas, puis rafraîchit les matviews de structures. La structure doit appartenir au périmètre d'extraction : `add_source_contribution_structure` l'y rattache."""
    ror = conn.execute(
        text(
            "UPDATE structures SET ror_id = COALESCE(ror_id, :ror) WHERE id = :id RETURNING ror_id"
        ),
        {"ror": f"0test{next(_seq):04d}", "id": structure_id},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO source_contribution_rors (source_contribution_id, ror_id) VALUES (:sc, :ror)"
        ),
        {"sc": source_contribution_id, "ror": ror},
    )
    refresh_structure_matviews(conn)


def add_source_contribution_structure(conn, source_contribution_id: int, structure_id: int) -> None:
    """Lie la contribution source `source_contribution_id` à `structure_id` par une adresse, rattache la structure au périmètre d'extraction, puis rafraîchit les matviews de structures."""
    raw_text = f"as-test-addr-{next(_seq)}"
    addr_id = insert_address(conn, raw_text, normalized_text=raw_text)
    insert_source_contribution_address(conn, source_contribution_id, address_id=addr_id)
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
