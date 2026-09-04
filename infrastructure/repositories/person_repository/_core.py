"""SQL d'écriture sur `persons`, `distinct_persons`, et la fusion."""

from sqlalchemy import Connection, text

from domain.errors import NotFoundError
from domain.normalize import normalize_name
from domain.persons.identifiers import AttributionStatus
from domain.persons.name_forms import PersonNameForm, compute_person_name_forms
from domain.persons.person import Person
from domain.persons.person_identifier import PersonIdentifier
from infrastructure.db.scalars import scalar_int
from infrastructure.repositories.person_repository import _name_forms


def find_by_id(conn: Connection, person_id: int) -> Person | None:
    row = conn.execute(
        text("""
            SELECT id, last_name, first_name,
                   last_name_normalized, first_name_normalized, rejected
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
        PersonIdentifier(
            id=r.id,
            person_id=r.person_id,
            id_type=r.id_type,
            id_value=r.id_value,
            status=AttributionStatus(r.status),
            source=r.source,
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
        rejected=row.rejected,
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


def set_rejected(conn: Connection, person_id: int, rejected: bool) -> None:
    result = conn.execute(
        text("UPDATE persons SET rejected = :r WHERE id = :id"),
        {"r": rejected, "id": person_id},
    )
    if result.rowcount == 0:
        raise NotFoundError(f"Personne {person_id} introuvable")
    # Le flag matérialisé `publications.in_perimeter` exclut les personnes rejetées (cf. `publication_in_perimeter`). Recalcule-le pour les publications de cette personne : son rejet/dé-rejet peut faire basculer leur appartenance.
    conn.execute(
        text("""
            UPDATE publications p
            SET in_perimeter = EXISTS (
                SELECT 1 FROM authorships a
                JOIN persons pe ON pe.id = a.person_id AND pe.rejected = FALSE
                WHERE a.publication_id = p.id AND a.in_perimeter = TRUE
            )
            WHERE p.id IN (SELECT publication_id FROM authorships WHERE person_id = :id)
              AND p.in_perimeter IS DISTINCT FROM EXISTS (
                SELECT 1 FROM authorships a
                JOIN persons pe ON pe.id = a.person_id AND pe.rejected = FALSE
                WHERE a.publication_id = p.id AND a.in_perimeter = TRUE
              )
        """),
        {"id": person_id},
    )


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


def has_distinct_rh(conn: Connection, id_a: int, id_b: int) -> bool:
    return (
        scalar_int(
            conn.execute(
                text("SELECT COUNT(*) AS n FROM persons_rh WHERE person_id IN (:a, :b)"),
                {"a": id_a, "b": id_b},
            )
        )
        >= 2
    )


def merge_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Séquence, dans la transaction du caller :
    1. Transfert source_authorships
    2. Dédoublonnage + transfert authorships vérité (+ rejected_authorships)
    3. Dédoublonnage + transfert identifiants
    4. Transfert conditionnel fiche RH
    5. person_name_forms : bascule source_id → target_id
    6. Recalcul des formes source 'persons' pour la cible
    7. Suppression de la personne source
    """
    conn.execute(
        text("UPDATE source_authorships SET person_id = :t WHERE person_id = :s"),
        {"t": target_id, "s": source_id},
    )
    conn.execute(
        text("""
            DELETE FROM authorships
            WHERE person_id = :s
              AND publication_id IN (
                  SELECT publication_id FROM authorships WHERE person_id = :t
              )
        """),
        {"s": source_id, "t": target_id},
    )
    conn.execute(
        text("UPDATE authorships SET person_id = :t WHERE person_id = :s"),
        {"t": target_id, "s": source_id},
    )
    # rejected_authorships : même motif dédup-puis-transfert. L'identité étant la même après fusion, un rejet sur l'absorbée vaut pour l'absorbante.
    conn.execute(
        text("""
            DELETE FROM rejected_authorships
            WHERE person_id = :s
              AND publication_id IN (
                  SELECT publication_id FROM rejected_authorships WHERE person_id = :t
              )
        """),
        {"s": source_id, "t": target_id},
    )
    conn.execute(
        text("UPDATE rejected_authorships SET person_id = :t WHERE person_id = :s"),
        {"t": target_id, "s": source_id},
    )
    conn.execute(
        text("UPDATE person_identifiers SET person_id = :t WHERE person_id = :s"),
        {"t": target_id, "s": source_id},
    )
    conn.execute(
        text("""
            UPDATE persons_rh SET person_id = :t
            WHERE person_id = :s
              AND NOT EXISTS (SELECT 1 FROM persons_rh WHERE person_id = :t)
        """),
        {"t": target_id, "s": source_id},
    )
    # Transférer les rows (name_form, source_id) vers (name_form, target_id) : UPSERT cross-person_id qui fusionne les sources si la name_form existe déjà côté target, puis DELETE des rows source résiduelles.
    conn.execute(
        text("""
            INSERT INTO person_name_forms (name_form, person_id, sources)
            SELECT name_form, :t, sources FROM person_name_forms WHERE person_id = :s
            ON CONFLICT (name_form, person_id) DO UPDATE SET
                sources = (
                    SELECT COALESCE(array_agg(DISTINCT s ORDER BY s), '{}'::text[])
                    FROM unnest(person_name_forms.sources || EXCLUDED.sources) AS s
                )
        """),
        {"t": target_id, "s": source_id},
    )
    conn.execute(
        text("DELETE FROM person_name_forms WHERE person_id = :s"),
        {"s": source_id},
    )
    target = conn.execute(
        text("SELECT last_name, first_name FROM persons WHERE id = :id"),
        {"id": target_id},
    ).one()
    forms = compute_person_name_forms(target.last_name, target.first_name or "")
    _name_forms.refresh_name_forms(conn, target_id, forms)
    conn.execute(text("DELETE FROM persons WHERE id = :id"), {"id": source_id})


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
