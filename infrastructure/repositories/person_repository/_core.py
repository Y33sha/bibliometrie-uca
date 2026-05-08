"""SQL d'écriture sur `persons`, `distinct_persons`, et la fusion.

Mode dispatch : chaque fonction accepte un curseur psycopg ou une
Connection SA. Phase 4 supprimera la branche psycopg.
"""

from typing import Any

from sqlalchemy import Connection, text

from domain.errors import NotFoundError
from domain.names import compute_person_name_forms
from domain.normalize import normalize_name
from infrastructure.db_helpers import row_val as _val
from infrastructure.repositories.person_repository import _name_forms


def create(conn: Any, last_name: str, first_name: str = "") -> int:
    if isinstance(conn, Connection):
        result = conn.execute(
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
        return result.scalar_one()
    conn.execute(
        """
        INSERT INTO persons (last_name, first_name,
                             last_name_normalized, first_name_normalized)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (last_name, first_name, normalize_name(last_name), normalize_name(first_name)),
    )
    return _val(conn.fetchone(), 0)


def update_name(conn: Any, person_id: int, last_name: str, first_name: str) -> None:
    if isinstance(conn, Connection):
        result = conn.execute(text("SELECT id FROM persons WHERE id = :id"), {"id": person_id})
        if result.first() is None:
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
        return
    conn.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
    if not conn.fetchone():
        raise NotFoundError(f"Personne {person_id} introuvable")

    conn.execute(
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


def set_rejected(conn: Any, person_id: int, rejected: bool) -> None:
    if isinstance(conn, Connection):
        result = conn.execute(
            text("UPDATE persons SET rejected = :r, updated_at = now() WHERE id = :id"),
            {"r": rejected, "id": person_id},
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Personne {person_id} introuvable")
        return
    conn.execute(
        "UPDATE persons SET rejected = %s, updated_at = now() WHERE id = %s",
        (rejected, person_id),
    )
    if conn.rowcount == 0:
        raise NotFoundError(f"Personne {person_id} introuvable")


def has_distinct_rh(conn: Any, id_a: int, id_b: int) -> bool:
    if isinstance(conn, Connection):
        result = conn.execute(
            text("SELECT COUNT(*) AS n FROM persons_rh WHERE person_id IN (:a, :b)"),
            {"a": id_a, "b": id_b},
        )
        return result.scalar_one() >= 2
    conn.execute(
        "SELECT COUNT(*) AS n FROM persons_rh WHERE person_id IN (%s, %s)",
        (id_a, id_b),
    )
    return _val(conn.fetchone(), 0) >= 2


def merge_into(conn: Any, target_id: int, source_id: int) -> None:
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
    """
    if isinstance(conn, Connection):
        # Toutes les étapes en text() — la complexité du merge ne tire pas
        # de bénéfice clair de SA Core, et préserve la lisibilité côte à
        # côte avec la branche psycopg.
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
        result = conn.execute(
            text("SELECT last_name, first_name FROM persons WHERE id = :id"),
            {"id": target_id},
        )
        target = result.one()
        forms = compute_person_name_forms(target.last_name, target.first_name or "")
        _name_forms.refresh_name_forms(conn, target_id, forms)
        conn.execute(text("DELETE FROM persons WHERE id = :id"), {"id": source_id})
        return

    # 1. Auteurs sources
    conn.execute(
        "UPDATE source_persons SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )
    # 1b. source_authorships
    conn.execute(
        "UPDATE source_authorships SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )

    # 2. authorships vérité (supprimer doublons publication)
    conn.execute(
        """
        DELETE FROM authorships
        WHERE person_id = %s
          AND publication_id IN (
              SELECT publication_id FROM authorships WHERE person_id = %s
          )
        """,
        (source_id, target_id),
    )
    conn.execute(
        "UPDATE authorships SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )

    # 3. identifiants (supprimer doublons)
    conn.execute(
        """
        DELETE FROM person_identifiers
        WHERE person_id = %s
          AND (id_type, id_value) IN (
              SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s
          )
        """,
        (source_id, target_id),
    )
    conn.execute(
        "UPDATE person_identifiers SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )

    # 4. fiche RH source → cible (si la cible n'en a pas)
    conn.execute(
        """
        UPDATE persons_rh SET person_id = %s
        WHERE person_id = %s
          AND NOT EXISTS (SELECT 1 FROM persons_rh WHERE person_id = %s)
        """,
        (target_id, source_id, target_id),
    )

    # 5. person_name_forms : remplacer source_id par target_id
    conn.execute(
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
    conn.execute(
        "SELECT last_name, first_name FROM persons WHERE id = %s",
        (target_id,),
    )
    target = conn.fetchone()
    forms = compute_person_name_forms(target["last_name"], target["first_name"] or "")
    _name_forms.refresh_name_forms(conn, target_id, forms)

    # 7. Supprimer la personne source
    conn.execute("DELETE FROM persons WHERE id = %s", (source_id,))


def mark_distinct(conn: Any, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
    """Marque deux personnes comme distinctes (idempotent). Retourne (a, b)
    triés si la paire vient d'être insérée, None si elle existait déjà."""
    if isinstance(conn, Connection):
        result = conn.execute(
            text("""
                INSERT INTO distinct_persons (person_id_a, person_id_b)
                VALUES (LEAST(:a, :b), GREATEST(:a, :b))
                ON CONFLICT DO NOTHING
                RETURNING person_id_a, person_id_b
            """),
            {"a": person_id_a, "b": person_id_b},
        )
        row = result.first()
        if not row:
            return None
        return row.person_id_a, row.person_id_b
    conn.execute(
        """
        INSERT INTO distinct_persons (person_id_a, person_id_b)
        VALUES (LEAST(%s, %s), GREATEST(%s, %s))
        ON CONFLICT DO NOTHING
        RETURNING person_id_a, person_id_b
        """,
        (person_id_a, person_id_b, person_id_a, person_id_b),
    )
    row = conn.fetchone()
    if not row:
        return None
    return _val(row, 0), _val(row, 1)
