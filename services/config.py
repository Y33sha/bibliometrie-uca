"""
Service Config — accès exclusif en écriture aux tables `config` et `perimeters`.

Les routers passent par ces fonctions pour toute écriture. Les lectures
restent autorisées dans les routers (convention du projet).
"""

import json

from domain.errors import ConflictError, NotFoundError, ValidationError

# ── Table config (clé / valeur JSON) ─────────────────────────────


def update_config_value(cur, key: str, value) -> dict:
    """Met à jour la valeur d'un paramètre de config existant.

    `value` est sérialisé en JSON. Retourne la ligne mise à jour.
    Lève NotFoundError si la clé n'existe pas.
    """
    cur.execute("SELECT key FROM config WHERE key = %s", (key,))
    if not cur.fetchone():
        raise NotFoundError(f"Paramètre '{key}' introuvable")

    cur.execute(
        """
        UPDATE config SET value = %s::jsonb, updated_at = now()
        WHERE key = %s
        RETURNING key, value, description, updated_at
        """,
        (json.dumps(value), key),
    )
    return cur.fetchone()


# ── Perimeters — structures membres ──────────────────────────────


def add_perimeter_structure(cur, perimeter_id: int, structure_id: int) -> str:
    """Ajoute une structure au périmètre (idempotent).

    Retourne :
      - "added" : la structure a été ajoutée au périmètre
      - "already_present" : la structure y était déjà

    Lève NotFoundError si le périmètre n'existe pas.
    """
    cur.execute(
        """
        UPDATE perimeters
        SET structure_ids = array_append(structure_ids, %s)
        WHERE id = %s AND NOT structure_ids @> ARRAY[%s]
        RETURNING id
        """,
        (structure_id, perimeter_id, structure_id),
    )
    if cur.fetchone():
        return "added"

    # Pas d'UPDATE → soit déjà présent, soit périmètre inexistant
    cur.execute("SELECT id FROM perimeters WHERE id = %s", (perimeter_id,))
    if cur.fetchone():
        return "already_present"
    raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


def remove_perimeter_structure(cur, perimeter_id: int, structure_id: int) -> None:
    """Retire une structure d'un périmètre (idempotent).

    Lève NotFoundError si le périmètre n'existe pas.
    """
    cur.execute(
        """
        UPDATE perimeters
        SET structure_ids = array_remove(structure_ids, %s)
        WHERE id = %s
        RETURNING id
        """,
        (structure_id, perimeter_id),
    )
    if not cur.fetchone():
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


# ── Perimeters — CRUD ────────────────────────────────────────────


def create_perimeter(cur, *, code: str, name: str, description: str | None = None) -> int:
    """Crée un nouveau périmètre. Retourne l'id créé.

    Lève ValidationError si code ou name est vide.
    Lève ConflictError si le code existe déjà.
    """
    if not code or not name:
        raise ValidationError("Code et nom requis")

    cur.execute("SELECT id FROM perimeters WHERE code = %s", (code,))
    if cur.fetchone():
        raise ConflictError(f"Le code '{code}' existe déjà")

    cur.execute(
        """
        INSERT INTO perimeters (code, name, description, structure_ids)
        VALUES (%s, %s, %s, '{}')
        RETURNING id
        """,
        (code, name, description),
    )
    return cur.fetchone()["id"]


def update_perimeter(cur, perimeter_id: int, *, fields: dict) -> None:
    """Met à jour un périmètre (name, description, structure_ids).

    Lève NotFoundError si le périmètre n'existe pas.
    Lève ValidationError si `fields` est vide ou ne contient aucun champ valide.
    """
    cur.execute("SELECT id FROM perimeters WHERE id = %s", (perimeter_id,))
    if not cur.fetchone():
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    allowed = {"name", "description", "structure_ids"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        raise ValidationError("Aucun champ à mettre à jour")

    sets = ", ".join(f"{k} = %s" for k in clean)
    cur.execute(
        f"UPDATE perimeters SET {sets} WHERE id = %s",
        list(clean.values()) + [perimeter_id],
    )


def perimeter_usage(cur, perimeter_code: str) -> list[str]:
    """Retourne la liste des clés config qui référencent ce périmètre
    (ex: ["perimeter_extraction", "perimeter_persons"]).
    """
    cur.execute(
        """
        SELECT key FROM config
        WHERE key LIKE 'perimeter_%%' AND value #>> '{}' = %s
        """,
        (perimeter_code,),
    )
    return [r["key"] for r in cur.fetchall()]


def delete_perimeter(cur, perimeter_id: int) -> None:
    """Supprime un périmètre.

    Lève NotFoundError si le périmètre n'existe pas.
    Lève ConflictError si le périmètre est utilisé par la config pipeline ;
    le message contient la liste des clés qui le référencent.
    """
    cur.execute("SELECT code FROM perimeters WHERE id = %s", (perimeter_id,))
    row = cur.fetchone()
    if not row:
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    used_by = perimeter_usage(cur, row["code"])
    if used_by:
        raise ConflictError(f"Ce périmètre est utilisé par : {', '.join(used_by)}")

    cur.execute("DELETE FROM perimeters WHERE id = %s", (perimeter_id,))
