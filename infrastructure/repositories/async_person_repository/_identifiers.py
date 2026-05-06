"""SQL async pour `person_identifiers`.

Mode dispatch : chaque fonction accepte un curseur psycopg ou une
AsyncConnection SA. Phase 4 supprimera la branche psycopg.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from domain.errors import NotFoundError


async def add_identifier(
    conn: Any,
    person_id: int,
    id_type: str,
    id_value: str,
    source: str = "auto",
    status: str = "pending",
) -> None:
    if isinstance(conn, AsyncConnection):
        await conn.execute(
            text("""
                INSERT INTO person_identifiers (person_id, id_type, id_value, source, status)
                VALUES (:pid, :it, :iv, :src, CAST(:st AS identifier_status))
                ON CONFLICT (id_type, id_value) DO UPDATE SET
                    person_id = EXCLUDED.person_id,
                    source = EXCLUDED.source,
                    status = 'pending'
                WHERE person_identifiers.status = 'rejected'
            """),
            {"pid": person_id, "it": id_type, "iv": id_value, "src": source, "st": status},
        )
        if id_type == "idhal":
            await conn.execute(
                text("""
                    UPDATE source_persons SET person_id = :pid
                    WHERE source = 'hal'
                      AND source_ids->>'idhal' = :iv
                      AND (person_id IS NULL OR person_id != :pid)
                """),
                {"pid": person_id, "iv": id_value},
            )
        return
    await conn.execute(
        """
        INSERT INTO person_identifiers (person_id, id_type, id_value, source, status)
        VALUES (%s, %s, %s, %s, %s::identifier_status)
        ON CONFLICT (id_type, id_value) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            source = EXCLUDED.source,
            status = 'pending'
        WHERE person_identifiers.status = 'rejected'
        """,
        (person_id, id_type, id_value, source, status),
    )

    if id_type == "idhal":
        await conn.execute(
            """
            UPDATE source_persons SET person_id = %s
            WHERE source = 'hal'
              AND source_ids->>'idhal' = %s
              AND (person_id IS NULL OR person_id != %s)
            """,
            (person_id, id_value, person_id),
        )


async def remove_identifier(conn: Any, person_id: int, id_type: str, id_value: str) -> None:
    if isinstance(conn, AsyncConnection):
        result = await conn.execute(
            text(
                "DELETE FROM person_identifiers "
                "WHERE person_id = :pid AND id_type = :it AND id_value = :iv"
            ),
            {"pid": person_id, "it": id_type, "iv": id_value},
        )
        if result.rowcount == 0:
            raise NotFoundError("Identifiant introuvable")
        return
    await conn.execute(
        """
        DELETE FROM person_identifiers
        WHERE person_id = %s AND id_type = %s AND id_value = %s
        """,
        (person_id, id_type, id_value),
    )
    if conn.rowcount == 0:
        raise NotFoundError("Identifiant introuvable")


async def update_identifier_status(conn: Any, ident_id: int, status: str) -> dict:
    if isinstance(conn, AsyncConnection):
        result = await conn.execute(
            text(
                "UPDATE person_identifiers SET status = CAST(:st AS identifier_status) "
                "WHERE id = :id RETURNING id, CAST(status AS text) AS status, person_id"
            ),
            {"st": status, "id": ident_id},
        )
        row = result.first()
        if not row:
            raise NotFoundError(f"Identifiant {ident_id} introuvable")
        return dict(row._mapping)
    await conn.execute(
        """
        UPDATE person_identifiers SET status = %s::identifier_status
        WHERE id = %s RETURNING id, status::text AS status, person_id
        """,
        (status, ident_id),
    )
    row = await conn.fetchone()
    if not row:
        raise NotFoundError(f"Identifiant {ident_id} introuvable")
    return row


async def reassign_identifier(conn: Any, ident_id: int, target_person_id: int) -> None:
    if isinstance(conn, AsyncConnection):
        result = await conn.execute(
            text(
                "UPDATE person_identifiers "
                "SET person_id = :pid, status = CAST('pending' AS identifier_status) "
                "WHERE id = :id"
            ),
            {"pid": target_person_id, "id": ident_id},
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Identifiant {ident_id} introuvable")
        return
    await conn.execute(
        """
        UPDATE person_identifiers
        SET person_id = %s, status = 'pending'::identifier_status
        WHERE id = %s
        """,
        (target_person_id, ident_id),
    )
    if conn.rowcount == 0:
        raise NotFoundError(f"Identifiant {ident_id} introuvable")
