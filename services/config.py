"""
Service Config — accès exclusif en écriture aux tables `config` et `perimeters`.

Les routers passent par ces fonctions pour toute écriture. Les lectures
restent autorisées dans les routers (convention du projet).
"""

import json


# ── Table config (clé / valeur JSON) ─────────────────────────────


def update_config_value(cur, key: str, value) -> dict | None:
    """Met à jour la valeur d'un paramètre de config existant.

    `value` est sérialisé en JSON. Retourne la ligne mise à jour
    {key, value, description, updated_at} ou None si la clé n'existe pas.
    """
    cur.execute("SELECT key FROM config WHERE key = %s", (key,))
    if not cur.fetchone():
        return None

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
      - "not_found" : le périmètre n'existe pas
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
    return "already_present" if cur.fetchone() else "not_found"


def remove_perimeter_structure(cur, perimeter_id: int, structure_id: int) -> bool:
    """Retire une structure d'un périmètre.

    Retourne True si le périmètre existe (array_remove est idempotent),
    False si le périmètre n'existe pas.
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
    return cur.fetchone() is not None


# ── Perimeters — CRUD ────────────────────────────────────────────


def create_perimeter(cur, *, code: str, name: str, description: str | None = None) -> int | None:
    """Crée un nouveau périmètre.

    Retourne l'id créé, ou None si le code existe déjà (conflit).
    """
    cur.execute("SELECT id FROM perimeters WHERE code = %s", (code,))
    if cur.fetchone():
        return None

    cur.execute(
        """
        INSERT INTO perimeters (code, name, description, structure_ids)
        VALUES (%s, %s, %s, '{}')
        RETURNING id
        """,
        (code, name, description),
    )
    return cur.fetchone()["id"]


def update_perimeter(cur, perimeter_id: int, *, fields: dict) -> bool:
    """Met à jour un périmètre (name, description, structure_ids).

    Retourne True si le périmètre existe et a été mis à jour, False sinon.
    Lève ValueError si `fields` est vide ou ne contient aucun champ valide.
    """
    cur.execute("SELECT id FROM perimeters WHERE id = %s", (perimeter_id,))
    if not cur.fetchone():
        return False

    allowed = {"name", "description", "structure_ids"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        raise ValueError("Aucun champ à mettre à jour")

    sets = ", ".join(f"{k} = %s" for k in clean)
    cur.execute(
        f"UPDATE perimeters SET {sets} WHERE id = %s",
        list(clean.values()) + [perimeter_id],
    )
    return True


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


def delete_perimeter(cur, perimeter_id: int) -> bool:
    """Supprime un périmètre.

    Retourne True si supprimé, False si introuvable.
    Lève ValueError si le périmètre est utilisé par la config pipeline ;
    le message contient la liste des clés qui le référencent.
    """
    cur.execute("SELECT code FROM perimeters WHERE id = %s", (perimeter_id,))
    row = cur.fetchone()
    if not row:
        return False

    used_by = perimeter_usage(cur, row["code"])
    if used_by:
        raise ValueError(f"Ce périmètre est utilisé par : {', '.join(used_by)}")

    cur.execute("DELETE FROM perimeters WHERE id = %s", (perimeter_id,))
    return True
