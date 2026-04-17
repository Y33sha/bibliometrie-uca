"""
Service Structures — accès exclusif en écriture aux tables
`structures`, `structure_relations`, `structure_name_forms`.

Les routers passent par ces fonctions pour toute écriture. Les lectures
restent autorisées dans les routers (convention du projet).
"""

from psycopg2.extras import Json
from pydantic import ValidationError as PydanticValidationError

from domain.errors import NotFoundError, ValidationError
from domain.structure import StructureApiIds
from services.audit import emit_event
from utils.normalize import normalize_text


def _validate_api_ids(raw: dict | None) -> dict | None:
    """Valide et normalise `api_ids` via le modèle domaine StructureApiIds.

    - Entrée : dict brut (côté API admin) ou None.
    - Sortie : dict canonique prêt pour JSONB, ou None si l'entrée
      est vide/None.
    - Lève ValidationError métier si le schéma est violé (type erroné,
      valeur non-string dans une liste, etc.).

    Le wrap PydanticValidationError → ValidationError garde le code
    HTTP 400 via les handlers globaux (sinon on aurait un 500).
    """
    if not raw:
        return None
    try:
        return StructureApiIds(**raw).to_dict() or None
    except PydanticValidationError as e:
        raise ValidationError(f"api_ids invalide : {e}") from e

# ── Mapping des champs UI → colonnes SQL pour la table structures ──
_STRUCTURE_FIELD_MAP = {
    "name": "name",
    "acronym": "acronym",
    "type": "structure_type",
    "ror_id": "ror_id",
    "rnsr_id": "rnsr_id",
    "hal_collection": "hal_collection",
}


# ── structures ────────────────────────────────────────────────────


def create_structure(
    cur,
    *,
    code: str,
    name: str,
    acronym: str | None = None,
    type: str,
    ror_id: str | None = None,
    rnsr_id: str | None = None,
    hal_collection: str | None = None,
    api_ids: dict | None = None,
) -> dict:
    """Crée une structure. Retourne la ligne insérée (RealDictRow)."""
    validated_api_ids = _validate_api_ids(api_ids)
    cur.execute(
        """
        INSERT INTO structures (code, name, acronym, structure_type, ror_id,
                                rnsr_id, hal_collection, api_ids)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, code, name, acronym, structure_type::text AS type,
                  ror_id, rnsr_id, hal_collection, api_ids
        """,
        (
            code, name, acronym, type, ror_id, rnsr_id, hal_collection,
            Json(validated_api_ids) if validated_api_ids else None,
        ),
    )
    return cur.fetchone()


def update_structure(cur, structure_id: int, *, fields: dict) -> dict:
    """Met à jour une structure. Retourne la ligne modifiée.

    Lève NotFoundError si la structure n'existe pas.
    Lève ValidationError si `fields` ne contient aucun champ valide.
    """
    cur.execute("SELECT id FROM structures WHERE id = %s", (structure_id,))
    if not cur.fetchone():
        raise NotFoundError(f"Structure {structure_id} introuvable")

    updates_sql = []
    params: list = []
    for field_name, col_name in _STRUCTURE_FIELD_MAP.items():
        val = fields.get(field_name)
        if val is not None:
            updates_sql.append(f"{col_name} = %s")
            params.append(val)

    if "api_ids" in fields and fields["api_ids"] is not None:
        validated = _validate_api_ids(fields["api_ids"])
        updates_sql.append("api_ids = %s")
        params.append(Json(validated) if validated else None)

    if not updates_sql:
        raise ValidationError("Aucun champ à mettre à jour")

    params.append(structure_id)
    cur.execute(
        f"""
        UPDATE structures SET {", ".join(updates_sql)} WHERE id = %s
        RETURNING id, code, name, acronym, structure_type::text AS type,
                  ror_id, rnsr_id, hal_collection, api_ids
        """,
        params,
    )
    return cur.fetchone()


def delete_structure(cur, structure_id: int) -> None:
    """Supprime une structure. Lève NotFoundError si elle n'existe pas."""
    cur.execute(
        "DELETE FROM structures WHERE id = %s RETURNING code, name",
        (structure_id,),
    )
    row = cur.fetchone()
    if not row:
        raise NotFoundError(f"Structure {structure_id} introuvable")
    emit_event(
        cur, "structure.deleted", "structure", structure_id,
        {"code": row["code"], "name": row["name"]},
    )


# ── structure_relations ───────────────────────────────────────────


def create_relation(cur, *, parent_id: int, child_id: int, relation_type: str) -> dict | None:
    """Crée une relation. Retourne la ligne insérée, ou None si elle existait déjà."""
    cur.execute(
        """
        INSERT INTO structure_relations (parent_id, child_id, relation_type)
        VALUES (%s, %s, %s)
        ON CONFLICT (parent_id, child_id, relation_type) DO NOTHING
        RETURNING *
        """,
        (parent_id, child_id, relation_type),
    )
    return cur.fetchone()


def delete_relation(cur, relation_id: int) -> None:
    """Supprime une relation. Lève NotFoundError si elle n'existe pas."""
    cur.execute(
        """DELETE FROM structure_relations WHERE id = %s
           RETURNING parent_id, child_id, relation_type::text AS relation_type""",
        (relation_id,),
    )
    row = cur.fetchone()
    if not row:
        raise NotFoundError(f"Relation {relation_id} introuvable")
    emit_event(
        cur, "structure_relation.deleted", "structure", row["parent_id"],
        {
            "relation_id": relation_id,
            "parent_id": row["parent_id"],
            "child_id": row["child_id"],
            "relation_type": row["relation_type"],
        },
    )


# ── structure_name_forms ──────────────────────────────────────────


def create_name_form(
    cur,
    *,
    structure_id: int,
    form_text: str,
    is_word_boundary: bool = False,
    is_excluding: bool = False,
    requires_context_of: list | None = None,
) -> dict:
    """Crée une forme de nom. Retourne la ligne insérée."""
    cur.execute(
        """
        INSERT INTO structure_name_forms (structure_id, form_text,
                                is_word_boundary, is_excluding, requires_context_of)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            structure_id,
            normalize_text(form_text),
            is_word_boundary,
            is_excluding,
            requires_context_of or None,
        ),
    )
    return cur.fetchone()


def update_name_form(cur, form_id: int, *, fields: dict) -> dict:
    """Met à jour une forme de nom. Retourne la ligne modifiée.

    Lève NotFoundError si la forme n'existe pas.
    Lève ValidationError si `fields` ne contient aucun champ valide.
    """
    cur.execute("SELECT id FROM structure_name_forms WHERE id = %s", (form_id,))
    if not cur.fetchone():
        raise NotFoundError(f"Forme {form_id} introuvable")

    updates_sql = []
    params: list = []

    if fields.get("form_text") is not None:
        updates_sql.append("form_text = %s")
        params.append(normalize_text(fields["form_text"]))
    if fields.get("is_word_boundary") is not None:
        updates_sql.append("is_word_boundary = %s")
        params.append(fields["is_word_boundary"])
    if fields.get("is_excluding") is not None:
        updates_sql.append("is_excluding = %s")
        params.append(fields["is_excluding"])
    if fields.get("requires_context_of") is not None:
        updates_sql.append("requires_context_of = %s")
        params.append(fields["requires_context_of"] or None)

    if not updates_sql:
        raise ValidationError("Aucun champ à mettre à jour")

    params.append(form_id)
    cur.execute(
        f"""
        UPDATE structure_name_forms SET {", ".join(updates_sql)}
        WHERE id = %s RETURNING *
        """,
        params,
    )
    return cur.fetchone()


def delete_name_form(cur, form_id: int) -> None:
    """Supprime une forme de nom. Lève NotFoundError si elle n'existe pas."""
    cur.execute(
        """DELETE FROM structure_name_forms WHERE id = %s
           RETURNING structure_id, form_text""",
        (form_id,),
    )
    row = cur.fetchone()
    if not row:
        raise NotFoundError(f"Forme {form_id} introuvable")
    emit_event(
        cur, "structure_name_form.deleted", "structure", row["structure_id"],
        {"form_id": form_id, "form_text": row["form_text"]},
    )
