"""SQL async pour `persons`, `distinct_persons`, et la fusion."""

from typing import Any

from domain.errors import NotFoundError
from domain.normalize import normalize_name
from domain.person import compute_person_name_forms
from infrastructure.db_helpers import row_val as _val
from infrastructure.repositories.async_person_repository import _name_forms


async def create(cur: Any, last_name: str, first_name: str = "") -> int:
    await cur.execute(
        """
        INSERT INTO persons (last_name, first_name,
                             last_name_normalized, first_name_normalized)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (last_name, first_name, normalize_name(last_name), normalize_name(first_name)),
    )
    return _val(await cur.fetchone(), 0)


async def update_name(cur: Any, person_id: int, last_name: str, first_name: str) -> None:
    await cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
    if not await cur.fetchone():
        raise NotFoundError(f"Personne {person_id} introuvable")

    await cur.execute(
        """
        UPDATE persons SET last_name = %s, first_name = %s,
               last_name_normalized = %s,
               first_name_normalized = %s,
               updated_at = now()
        WHERE id = %s
        """,
        (
            last_name,
            first_name,
            normalize_name(last_name),
            normalize_name(first_name),
            person_id,
        ),
    )


async def set_rejected(cur: Any, person_id: int, rejected: bool) -> None:
    await cur.execute(
        "UPDATE persons SET rejected = %s, updated_at = now() WHERE id = %s",
        (rejected, person_id),
    )
    if cur.rowcount == 0:
        raise NotFoundError(f"Personne {person_id} introuvable")


async def has_distinct_rh(cur: Any, id_a: int, id_b: int) -> bool:
    await cur.execute(
        "SELECT COUNT(*) AS n FROM persons_rh WHERE person_id IN (%s, %s)",
        (id_a, id_b),
    )
    return _val(await cur.fetchone(), 0) >= 2


async def merge_into(cur: Any, target_id: int, source_id: int) -> None:
    # 1. Auteurs sources
    await cur.execute(
        "UPDATE source_persons SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )
    # 1b. source_authorships
    await cur.execute(
        "UPDATE source_authorships SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )

    # 2. authorships vérité (supprimer doublons publication)
    await cur.execute(
        """
        DELETE FROM authorships
        WHERE person_id = %s
          AND publication_id IN (
              SELECT publication_id FROM authorships WHERE person_id = %s
          )
        """,
        (source_id, target_id),
    )
    await cur.execute(
        "UPDATE authorships SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )

    # 3. identifiants (supprimer doublons)
    await cur.execute(
        """
        DELETE FROM person_identifiers
        WHERE person_id = %s
          AND (id_type, id_value) IN (
              SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s
          )
        """,
        (source_id, target_id),
    )
    await cur.execute(
        "UPDATE person_identifiers SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )

    # 4. fiche RH source → cible (si la cible n'en a pas)
    await cur.execute(
        """
        UPDATE persons_rh SET person_id = %s
        WHERE person_id = %s
          AND NOT EXISTS (SELECT 1 FROM persons_rh WHERE person_id = %s)
        """,
        (target_id, source_id, target_id),
    )

    # 5. person_name_forms : remplacer source_id par target_id
    await cur.execute(
        """
        UPDATE person_name_forms
        SET person_ids = (
                SELECT array_agg(DISTINCT v ORDER BY v)
                FROM unnest(array_replace(person_ids, %s, %s)) AS v
            ),
            updated_at = now()
        WHERE %s = ANY(person_ids)
        """,
        (source_id, target_id, source_id),
    )

    # 6. Recalculer les formes source 'persons' de la cible
    await cur.execute(
        "SELECT last_name, first_name FROM persons WHERE id = %s",
        (target_id,),
    )
    target = await cur.fetchone()
    forms = compute_person_name_forms(target["last_name"], target["first_name"] or "")
    await _name_forms.refresh_name_forms(cur, target_id, forms)

    # 7. Supprimer la personne source
    await cur.execute("DELETE FROM persons WHERE id = %s", (source_id,))


async def mark_distinct(cur: Any, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
    await cur.execute(
        """
        INSERT INTO distinct_persons (person_id_a, person_id_b)
        VALUES (LEAST(%s, %s), GREATEST(%s, %s))
        ON CONFLICT DO NOTHING
        RETURNING person_id_a, person_id_b
        """,
        (person_id_a, person_id_b, person_id_a, person_id_b),
    )
    row = await cur.fetchone()
    if not row:
        return None
    return _val(row, 0), _val(row, 1)
