"""SQL d'écriture sur `persons`, `distinct_persons`, et la fusion."""

from sqlalchemy import Connection, text

from domain.errors import NotFoundError
from domain.normalize import normalize_name
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

    nf_rows = conn.execute(
        text(
            "SELECT DISTINCT name_form FROM person_name_forms "
            "WHERE person_id = :pid ORDER BY name_form"
        ),
        {"pid": person_id},
    ).all()
    name_forms = tuple(PersonNameForm(value=r.name_form) for r in nf_rows)

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
                "lnn": normalize_name(last_name),
                "fnn": normalize_name(first_name),
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
            "lnn": normalize_name(last_name),
            "fnn": normalize_name(first_name),
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


def find_rh_person_duplicate(
    conn: Connection, last_name: str, first_name: str, department: str | None, role: str | None
) -> int | None:
    row = conn.execute(
        text("""
            SELECT p.id FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.last_name_normalized = :ln
              AND p.first_name_normalized = :fn
              AND prh.department_name IS NOT DISTINCT FROM :dept
              AND prh.role_title IS NOT DISTINCT FROM :role
        """),
        {
            "ln": normalize_name(last_name),
            "fn": normalize_name(first_name),
            "dept": department,
            "role": role,
        },
    ).first()
    return row.id if row else None


def insert_rh_record(
    conn: Connection,
    person_id: int,
    *,
    email: str | None,
    role: str | None,
    department: str | None,
    start_date: str | None,
    end_date: str | None,
    export_date: str | None,
) -> None:
    conn.execute(
        text("""
            INSERT INTO persons_rh
                (person_id, email, role_title, department_name,
                 start_date, end_date, hr_export_date)
            VALUES (:pid, :email, :role, :dept, :start, :end, :exp)
        """),
        {
            "pid": person_id,
            "email": email,
            "role": role,
            "dept": department,
            "start": start_date,
            "end": end_date,
            "exp": export_date,
        },
    )


def map_rh_emails_to_person_ids(conn: Connection) -> dict[str, list[int]]:
    """`{email minusculisé: [person_id, ...]}` depuis `persons_rh` (emails renseignés). Résout les emails de l'import des ORCID authentifiés vers les personnes qui les portent."""
    return {
        r.email: list(r.pids)
        for r in conn.execute(
            text(
                "SELECT lower(email) AS email, array_agg(DISTINCT person_id) AS pids "
                "FROM persons_rh WHERE email IS NOT NULL GROUP BY lower(email)"
            )
        )
    }


def ids_with_rh(conn: Connection, person_ids: list[int]) -> set[int]:
    return set(
        conn.execute(
            text("SELECT DISTINCT person_id FROM persons_rh WHERE person_id = ANY(:ids)"),
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
