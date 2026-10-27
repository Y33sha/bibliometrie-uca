"""SQL d'écriture sur `persons`, `distinct_persons`, et la fusion."""

from sqlalchemy import Connection, text

from domain.errors import NotFoundError
from domain.normalize import normalize_text
from domain.persons.identifier_attribution import IdentifierAttribution
from domain.persons.identifiers import AttributionStatus, IdentifierOrigin
from domain.persons.name_forms import PersonNameForm
from domain.persons.person import Person, PersonExclusion
from infrastructure.db.scalars import scalar_int


def find_by_id(conn: Connection, person_id: int) -> Person | None:
    row = conn.execute(
        text("""
            SELECT id, last_name, first_name,
                   last_name_normalized, first_name_normalized, exclusion
            FROM persons WHERE id = :id
        """),
        {"id": person_id},
    ).first()
    if row is None:
        return None

    id_rows = conn.execute(
        text("""
            SELECT id, person_id, id_type, id_value, source,
                   CAST(status AS text) AS status
            FROM person_identifiers
            WHERE person_id = :pid
        """),
        {"pid": person_id},
    ).all()
    identifiers = tuple(
        IdentifierAttribution(
            id=r.id,
            person_id=r.person_id,
            id_type=r.id_type,
            id_value=r.id_value,
            status=AttributionStatus(r.status),
            source=IdentifierOrigin(r.source),
        )
        for r in id_rows
    )

    name_form_rows = conn.execute(
        text(
            "SELECT DISTINCT name_form FROM person_name_forms "
            "WHERE person_id = :pid ORDER BY name_form"
        ),
        {"pid": person_id},
    ).all()
    name_forms = tuple(PersonNameForm(value=r.name_form) for r in name_form_rows)

    return Person(
        id=row.id,
        last_name=row.last_name,
        first_name=row.first_name,
        last_name_normalized=row.last_name_normalized,
        first_name_normalized=row.first_name_normalized,
        exclusion=PersonExclusion(row.exclusion) if row.exclusion else None,
        identifiers=identifiers,
        name_forms=name_forms,
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
