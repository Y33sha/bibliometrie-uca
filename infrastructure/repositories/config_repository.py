"""Adapter PostgreSQL pour `config` et `perimeters`.

Les opérations sont toutes très simples : chaque méthode = un SELECT
ou un UPDATE/DELETE/INSERT ciblé. La logique métier (validation des
codes, détection d'usage avant suppression) reste dans le service.
"""

import json
from typing import Any


class PgConfigRepository:
    """Accès PostgreSQL aux agrégats Config et Perimeter."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    # ── Table config (clé / valeur JSON) ───────────────────────────

    def config_key_exists(self, key: str) -> bool:
        """Vrai si une clé existe dans la table config."""
        self._cur.execute("SELECT key FROM config WHERE key = %s", (key,))
        return self._cur.fetchone() is not None

    def update_config_value(self, key: str, value: Any) -> dict:
        """UPDATE la valeur JSON d'une clé. Retourne la ligne mise à jour
        (ou None si la clé n'existe pas — le service vérifie l'existence
        au préalable)."""
        self._cur.execute(
            """
            UPDATE config SET value = %s::jsonb, updated_at = now()
            WHERE key = %s
            RETURNING key, value, description, updated_at
            """,
            (json.dumps(value), key),
        )
        return self._cur.fetchone()

    def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        """Retourne les clés config (préfixe 'perimeter_') qui référencent
        ce code de périmètre."""
        self._cur.execute(
            """
            SELECT key FROM config
            WHERE key LIKE 'perimeter_%%' AND value #>> '{}' = %s
            """,
            (perimeter_code,),
        )
        return [r["key"] for r in self._cur.fetchall()]

    # ── Perimeters — structures membres ────────────────────────────

    def add_structure_to_perimeter(
        self,
        perimeter_id: int,
        structure_id: int,
    ) -> bool:
        """Ajoute la structure au périmètre si absente. Retourne True si
        l'ajout a eu lieu, False sinon (déjà présente ou périmètre
        inexistant — le service distingue les deux via perimeter_exists)."""
        self._cur.execute(
            """
            UPDATE perimeters
            SET structure_ids = array_append(structure_ids, %s)
            WHERE id = %s AND NOT structure_ids @> ARRAY[%s]
            RETURNING id
            """,
            (structure_id, perimeter_id, structure_id),
        )
        return self._cur.fetchone() is not None

    def remove_structure_from_perimeter(
        self,
        perimeter_id: int,
        structure_id: int,
    ) -> bool:
        """Retire la structure du périmètre (idempotent). Retourne True si
        le périmètre existe, False sinon."""
        self._cur.execute(
            """
            UPDATE perimeters
            SET structure_ids = array_remove(structure_ids, %s)
            WHERE id = %s
            RETURNING id
            """,
            (structure_id, perimeter_id),
        )
        return self._cur.fetchone() is not None

    # ── Perimeters — CRUD ──────────────────────────────────────────

    def perimeter_exists(self, perimeter_id: int) -> bool:
        """Vrai si le périmètre existe."""
        self._cur.execute(
            "SELECT id FROM perimeters WHERE id = %s",
            (perimeter_id,),
        )
        return self._cur.fetchone() is not None

    def perimeter_code_exists(self, code: str) -> bool:
        """Vrai si un périmètre avec ce code existe déjà."""
        self._cur.execute(
            "SELECT id FROM perimeters WHERE code = %s",
            (code,),
        )
        return self._cur.fetchone() is not None

    def create_perimeter(
        self,
        *,
        code: str,
        name: str,
        description: str | None,
    ) -> int:
        """Insère un périmètre avec structure_ids=[]. Retourne son id."""
        self._cur.execute(
            """
            INSERT INTO perimeters (code, name, description, structure_ids)
            VALUES (%s, %s, %s, '{}')
            RETURNING id
            """,
            (code, name, description),
        )
        return self._cur.fetchone()["id"]

    def update_perimeter_fields(self, perimeter_id: int, fields: dict) -> None:
        """UPDATE dynamique des champs autorisés. Le service filtre déjà
        les clés interdites — ce repo ne valide pas."""
        sets = ", ".join(f"{k} = %s" for k in fields)
        self._cur.execute(
            f"UPDATE perimeters SET {sets} WHERE id = %s",
            list(fields.values()) + [perimeter_id],
        )

    def get_perimeter_code(self, perimeter_id: int) -> str | None:
        """Retourne le code d'un périmètre, ou None."""
        self._cur.execute(
            "SELECT code FROM perimeters WHERE id = %s",
            (perimeter_id,),
        )
        row = self._cur.fetchone()
        return row["code"] if row else None

    def delete_perimeter(self, perimeter_id: int) -> None:
        """Supprime un périmètre. Le service doit avoir vérifié l'absence
        de références dans config au préalable."""
        self._cur.execute(
            "DELETE FROM perimeters WHERE id = %s",
            (perimeter_id,),
        )
