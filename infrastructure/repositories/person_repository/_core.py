"""SQL d'écriture sur `persons`, `distinct_persons`, et la fusion."""

from sqlalchemy import Connection, text

from domain.errors import NotFoundError
from domain.names import compute_person_name_forms
from domain.normalize import normalize_name
from infrastructure.repositories.person_repository import _name_forms


def create(conn: Connection, last_name: str, first_name: str = "") -> int:
    return conn.execute(
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
    ).scalar_one()


def update_name(conn: Connection, person_id: int, last_name: str, first_name: str) -> None:
    if (
        conn.execute(text("SELECT id FROM persons WHERE id = :id"), {"id": person_id}).first()
        is None
    ):
        raise NotFoundError(f"Personne {person_id} introuvable")
    conn.execute(
        text(
            "UPDATE persons SET last_name = :ln, first_name = :fn, "
            "last_name_normalized = :lnn, first_name_normalized = :fnn, "
            "updated_at = now() WHERE id = :id"
        ),
        {
            "ln": last_name,
            "fn": first_name,
            "lnn": normalize_name(last_name),
            "fnn": normalize_name(first_name),
            "id": person_id,
        },
    )


def set_rejected(conn: Connection, person_id: int, rejected: bool) -> None:
    result = conn.execute(
        text("UPDATE persons SET rejected = :r, updated_at = now() WHERE id = :id"),
        {"r": rejected, "id": person_id},
    )
    if result.rowcount == 0:
        raise NotFoundError(f"Personne {person_id} introuvable")


def has_distinct_rh(conn: Connection, id_a: int, id_b: int) -> bool:
    return (
        conn.execute(
            text("SELECT COUNT(*) AS n FROM persons_rh WHERE person_id IN (:a, :b)"),
            {"a": id_a, "b": id_b},
        ).scalar_one()
        >= 2
    )


def merge_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Fusionne `source_id` dans `target_id`.

    Séquence complète en une transaction :
    1. Transfert auteurs sources + source_authorships
    2. Dédoublonnage + transfert authorships vérité
    3. Dédoublonnage + transfert identifiants
    4. Transfert conditionnel fiche RH
    5. person_name_forms : remplacement source_id → target_id
    6. Recalcul des formes source 'persons' pour la cible
    7. Suppression de la personne source

    L'invariant (pas de fusion si les deux ont une fiche RH) doit être
    vérifié avant par le service via `has_distinct_rh`.

    Tout en `text()` : la complexité du merge ne tire pas de bénéfice
    clair de SA Core (cross-aggregate sur 7 tables).
    """
    conn.execute(
        text("UPDATE source_persons SET person_id = :t WHERE person_id = :s"),
        {"t": target_id, "s": source_id},
    )
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
    conn.execute(
        text("""
            DELETE FROM person_identifiers
            WHERE person_id = :s
              AND (id_type, id_value) IN (
                  SELECT id_type, id_value FROM person_identifiers WHERE person_id = :t
              )
        """),
        {"s": source_id, "t": target_id},
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
    conn.execute(
        text("""
            UPDATE person_name_forms
            SET person_ids = (
                    SELECT array_agg(DISTINCT v ORDER BY v)
                    FROM unnest(array_replace(person_ids, :s, :t)) AS v
                ),
                updated_at = now()
            WHERE :s = ANY(person_ids)
        """),
        {"s": source_id, "t": target_id},
    )
    target = conn.execute(
        text("SELECT last_name, first_name FROM persons WHERE id = :id"),
        {"id": target_id},
    ).one()
    forms = compute_person_name_forms(target.last_name, target.first_name or "")
    _name_forms.refresh_name_forms(conn, target_id, forms)
    conn.execute(text("DELETE FROM persons WHERE id = :id"), {"id": source_id})


def mark_distinct(conn: Connection, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
    """Marque deux personnes comme distinctes (idempotent). Retourne (a, b)
    triés si la paire vient d'être insérée, None si elle existait déjà."""
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
