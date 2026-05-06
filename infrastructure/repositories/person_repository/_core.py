"""SQL d'écriture sur `persons`, `distinct_persons`, et la fusion."""

from typing import Any

from domain.errors import NotFoundError
from domain.names import compute_person_name_forms
from domain.normalize import normalize_name
from infrastructure.db_helpers import row_val as _val
from infrastructure.repositories.person_repository import _name_forms


def create(cur: Any, last_name: str, first_name: str = "") -> int:
    cur.execute(
        """
        INSERT INTO persons (last_name, first_name,
                             last_name_normalized, first_name_normalized)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (last_name, first_name, normalize_name(last_name), normalize_name(first_name)),
    )
    return _val(cur.fetchone(), 0)


def update_name(cur: Any, person_id: int, last_name: str, first_name: str) -> None:
    cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
    if not cur.fetchone():
        raise NotFoundError(f"Personne {person_id} introuvable")

    cur.execute(
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


def set_rejected(cur: Any, person_id: int, rejected: bool) -> None:
    cur.execute(
        "UPDATE persons SET rejected = %s, updated_at = now() WHERE id = %s",
        (rejected, person_id),
    )
    if cur.rowcount == 0:
        raise NotFoundError(f"Personne {person_id} introuvable")


def has_distinct_rh(cur: Any, id_a: int, id_b: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) AS n FROM persons_rh WHERE person_id IN (%s, %s)",
        (id_a, id_b),
    )
    return _val(cur.fetchone(), 0) >= 2


def merge_into(cur: Any, target_id: int, source_id: int) -> None:
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
    # 1. Auteurs sources
    cur.execute(
        "UPDATE source_persons SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )
    # 1b. source_authorships
    cur.execute(
        "UPDATE source_authorships SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )

    # 2. authorships vérité (supprimer doublons publication)
    cur.execute(
        """
        DELETE FROM authorships
        WHERE person_id = %s
          AND publication_id IN (
              SELECT publication_id FROM authorships WHERE person_id = %s
          )
        """,
        (source_id, target_id),
    )
    cur.execute(
        "UPDATE authorships SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )

    # 3. identifiants (supprimer doublons)
    cur.execute(
        """
        DELETE FROM person_identifiers
        WHERE person_id = %s
          AND (id_type, id_value) IN (
              SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s
          )
        """,
        (source_id, target_id),
    )
    cur.execute(
        "UPDATE person_identifiers SET person_id = %s WHERE person_id = %s",
        (target_id, source_id),
    )

    # 4. fiche RH source → cible (si la cible n'en a pas)
    cur.execute(
        """
        UPDATE persons_rh SET person_id = %s
        WHERE person_id = %s
          AND NOT EXISTS (SELECT 1 FROM persons_rh WHERE person_id = %s)
        """,
        (target_id, source_id, target_id),
    )

    # 5. person_name_forms : remplacer source_id par target_id
    cur.execute(
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
    cur.execute(
        "SELECT last_name, first_name FROM persons WHERE id = %s",
        (target_id,),
    )
    target = cur.fetchone()
    forms = compute_person_name_forms(target["last_name"], target["first_name"] or "")
    _name_forms.refresh_name_forms(cur, target_id, forms)

    # 7. Supprimer la personne source
    cur.execute("DELETE FROM persons WHERE id = %s", (source_id,))


def mark_distinct(cur: Any, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
    """Marque deux personnes comme distinctes (idempotent). Retourne (a, b)
    triés si la paire vient d'être insérée, None si elle existait déjà."""
    cur.execute(
        """
        INSERT INTO distinct_persons (person_id_a, person_id_b)
        VALUES (LEAST(%s, %s), GREATEST(%s, %s))
        ON CONFLICT DO NOTHING
        RETURNING person_id_a, person_id_b
        """,
        (person_id_a, person_id_b, person_id_a, person_id_b),
    )
    row = cur.fetchone()
    if not row:
        return None
    return _val(row, 0), _val(row, 1)
