"""SQL d'écriture sur `persons`, `distinct_persons`, et la fusion."""

from sqlalchemy import Connection, text

from domain.errors import NotFoundError
from domain.normalize import normalize_text
from domain.persons.person import PersonExclusion
from infrastructure.db.scalars import scalar_int


def exists(conn: Connection, person_id: int) -> bool:
    return bool(
        conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM persons WHERE id = :id)"), {"id": person_id}
        ).scalar()
    )


def create(conn: Connection, last_name: str, first_name: str = "") -> int:
    return scalar_int(
        conn.execute(
            text(
                "INSERT INTO persons (last_name, first_name, "
                "last_name_normalized, first_name_normalized) "
                "VALUES (:ln, :fn, :lnn, :fnn) RETURNING id"
            ),
            {
                "ln": last_name,
                "fn": first_name,
                "lnn": normalize_text(last_name),
                "fnn": normalize_text(first_name),
            },
        )
    )


def update_name(conn: Connection, person_id: int, last_name: str, first_name: str) -> None:
    result = conn.execute(
        text(
            "UPDATE persons SET last_name = :ln, first_name = :fn, "
            "last_name_normalized = :lnn, first_name_normalized = :fnn "
            "WHERE id = :id"
        ),
        {
            "ln": last_name,
            "fn": first_name,
            "lnn": normalize_text(last_name),
            "fnn": normalize_text(first_name),
            "id": person_id,
        },
    )
    if result.rowcount == 0:
        raise NotFoundError(f"Personne {person_id} introuvable")


def set_exclusion(conn: Connection, person_id: int, exclusion: PersonExclusion | None) -> None:
    result = conn.execute(
        text("UPDATE persons SET exclusion = CAST(:e AS person_exclusion) WHERE id = :id"),
        {"e": exclusion.value if exclusion else None, "id": person_id},
    )
    if result.rowcount == 0:
        raise NotFoundError(f"Personne {person_id} introuvable")


def ids_with_rh(conn: Connection, person_ids: list[int]) -> set[int]:
    return set(
        conn.execute(
            text("SELECT DISTINCT person_id FROM hr_records WHERE person_id = ANY(:ids)"),
            {"ids": person_ids},
        ).scalars()
    )


def mark_distinct(conn: Connection, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
    row = conn.execute(
        text("""
            INSERT INTO distinct_persons (person_id_a, person_id_b)
            VALUES (LEAST(:a, :b), GREATEST(:a, :b))
            ON CONFLICT DO NOTHING
            RETURNING person_id_a, person_id_b
        """),
        {"a": person_id_a, "b": person_id_b},
    ).first()
    if not row:
        return None
    return row.person_id_a, row.person_id_b


def unmark_distinct(conn: Connection, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
    row = conn.execute(
        text("""
            DELETE FROM distinct_persons
            WHERE person_id_a = LEAST(:a, :b) AND person_id_b = GREATEST(:a, :b)
            RETURNING person_id_a, person_id_b
        """),
        {"a": person_id_a, "b": person_id_b},
    ).first()
    if not row:
        return None
    return row.person_id_a, row.person_id_b
