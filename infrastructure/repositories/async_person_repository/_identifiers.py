"""SQL async pour `person_identifiers`."""

from typing import Any

from domain.errors import NotFoundError


async def add_identifier(
    cur: Any,
    person_id: int,
    id_type: str,
    id_value: str,
    source: str = "auto",
    status: str = "pending",
) -> None:
    await cur.execute(
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
        await cur.execute(
            """
            UPDATE source_persons SET person_id = %s
            WHERE source = 'hal'
              AND source_ids->>'idhal' = %s
              AND (person_id IS NULL OR person_id != %s)
            """,
            (person_id, id_value, person_id),
        )


async def remove_identifier(cur: Any, person_id: int, id_type: str, id_value: str) -> None:
    await cur.execute(
        """
        DELETE FROM person_identifiers
        WHERE person_id = %s AND id_type = %s AND id_value = %s
        """,
        (person_id, id_type, id_value),
    )
    if cur.rowcount == 0:
        raise NotFoundError("Identifiant introuvable")


async def update_identifier_status(cur: Any, ident_id: int, status: str) -> dict:
    await cur.execute(
        """
        UPDATE person_identifiers SET status = %s::identifier_status
        WHERE id = %s RETURNING id, status::text AS status, person_id
        """,
        (status, ident_id),
    )
    row = await cur.fetchone()
    if not row:
        raise NotFoundError(f"Identifiant {ident_id} introuvable")
    return row


async def reassign_identifier(cur: Any, ident_id: int, target_person_id: int) -> None:
    await cur.execute(
        """
        UPDATE person_identifiers
        SET person_id = %s, status = 'pending'::identifier_status
        WHERE id = %s
        """,
        (target_person_id, ident_id),
    )
    if cur.rowcount == 0:
        raise NotFoundError(f"Identifiant {ident_id} introuvable")
