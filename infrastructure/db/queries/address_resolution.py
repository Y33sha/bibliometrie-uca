"""Query service : SQL du pipeline de résolution d'adresses.

Appelé par `application/pipeline/addresses/resolve_addresses.py`.
Regroupe les opérations SQL de la boucle de matching adresses → structures
(détection automatique via `structure_name_forms`).

Séparé de `infrastructure/db/queries/addresses.py`, qui sert la couche API
(lecture/CRUD des adresses). Ici : écritures de la pipeline.
"""

from typing import Any

from infrastructure.db_helpers import rows_as_dicts


def load_name_forms(cur: Any) -> list[dict[str, Any]]:
    """Charge toutes les formes depuis `structure_name_forms` + infos structure."""
    cur.execute("""
        SELECT nf.id, nf.structure_id, nf.form_text,
               nf.is_word_boundary, nf.requires_context_of,
               nf.is_excluding,
               s.code AS struct_code, s.structure_type::text AS struct_type
        FROM structure_name_forms nf
        JOIN structures s ON s.id = nf.structure_id
        ORDER BY nf.id
    """)
    return rows_as_dicts(cur)


def reset_auto_detected(cur: Any) -> int:
    """Supprime les liens `address_structures` auto-détectés. Retourne le rowcount."""
    cur.execute("DELETE FROM address_structures WHERE matched_form_id IS NOT NULL")
    return cur.rowcount


def reset_all_resolved_at(cur: Any) -> None:
    """Remet `addresses.resolved_at` à NULL pour forcer un recalcul complet."""
    cur.execute("UPDATE addresses SET resolved_at = NULL")


def fetch_addresses_to_resolve(cur: Any, *, incremental: bool) -> list[tuple[int, str]]:
    """Retourne `(id, raw_text)` des adresses à traiter.

    Si `incremental=True` : uniquement celles avec `resolved_at IS NULL`.
    Sinon : toutes les adresses.

    Conversion explicite dict → tuple : la connexion pipeline utilise
    `row_factory=dict_row`, donc `fetchall` retourne des dicts. L'appelant
    unpacke `(addr_id, raw_text)` : sans conversion, il récupérerait les
    clés "id"/"raw_text" au lieu des valeurs.
    """
    if incremental:
        cur.execute(
            "SELECT a.id, a.raw_text FROM addresses a WHERE a.resolved_at IS NULL ORDER BY a.id"
        )
    else:
        cur.execute("SELECT a.id, a.raw_text FROM addresses a ORDER BY a.id")
    return [(row["id"], row["raw_text"]) for row in cur.fetchall()]


def delete_obsolete_detections(cur: Any, addr_id: int, kept_structure_ids: list[int]) -> int:
    """Supprime les liens auto-détectés devenus obsolètes (non confirmés).

    `kept_structure_ids` : structures toujours détectées (à garder).
    Les liens `matched_form_id IS NOT NULL` vers d'autres structures et
    `is_confirmed IS NULL` sont supprimés. Retourne le rowcount.
    """
    if kept_structure_ids:
        cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = %s
              AND matched_form_id IS NOT NULL
              AND structure_id != ALL(%s)
              AND is_confirmed IS NULL
            """,
            (addr_id, kept_structure_ids),
        )
    else:
        cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = %s
              AND matched_form_id IS NOT NULL
              AND is_confirmed IS NULL
            """,
            (addr_id,),
        )
    return cur.rowcount


def unflag_obsolete_detections(cur: Any, addr_id: int, kept_structure_ids: list[int]) -> None:
    """Retire `matched_form_id` sur les liens obsolètes confirmés/rejetés manuellement.

    Les liens manuels (is_confirmed IS NOT NULL) ne sont pas supprimés,
    mais perdent leur marqueur de détection auto.
    """
    if kept_structure_ids:
        cur.execute(
            """
            UPDATE address_structures
            SET matched_form_id = NULL
            WHERE address_id = %s
              AND matched_form_id IS NOT NULL
              AND structure_id != ALL(%s)
              AND is_confirmed IS NOT NULL
            """,
            (addr_id, kept_structure_ids),
        )
    else:
        cur.execute(
            """
            UPDATE address_structures
            SET matched_form_id = NULL
            WHERE address_id = %s
              AND matched_form_id IS NOT NULL
              AND is_confirmed IS NOT NULL
            """,
            (addr_id,),
        )


def upsert_detected_structure(cur: Any, addr_id: int, structure_id: int, form_id: int) -> None:
    """Crée ou met à jour le lien `address_structures` avec le form_id détecté."""
    cur.execute(
        """
        INSERT INTO address_structures
            (address_id, structure_id, matched_form_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (address_id, structure_id)
            DO UPDATE SET matched_form_id = EXCLUDED.matched_form_id
        """,
        (addr_id, structure_id, form_id),
    )


def mark_address_resolved(cur: Any, addr_id: int) -> None:
    """Marque une adresse comme résolue (`resolved_at = now()`)."""
    cur.execute("UPDATE addresses SET resolved_at = now() WHERE id = %s", (addr_id,))


class PgAddressResolutionQueries:
    """Adapter PostgreSQL pour `application.ports.address_resolution.AddressResolutionQueries`."""

    def load_name_forms(self, cur: Any) -> list[dict[str, Any]]:
        return load_name_forms(cur)

    def reset_auto_detected(self, cur: Any) -> int:
        return reset_auto_detected(cur)

    def reset_all_resolved_at(self, cur: Any) -> None:
        reset_all_resolved_at(cur)

    def fetch_addresses_to_resolve(self, cur: Any, *, incremental: bool) -> list[tuple[int, str]]:
        return fetch_addresses_to_resolve(cur, incremental=incremental)

    def delete_obsolete_detections(
        self, cur: Any, addr_id: int, kept_structure_ids: list[int]
    ) -> int:
        return delete_obsolete_detections(cur, addr_id, kept_structure_ids)

    def unflag_obsolete_detections(
        self, cur: Any, addr_id: int, kept_structure_ids: list[int]
    ) -> None:
        unflag_obsolete_detections(cur, addr_id, kept_structure_ids)

    def upsert_detected_structure(
        self, cur: Any, addr_id: int, structure_id: int, form_id: int
    ) -> None:
        upsert_detected_structure(cur, addr_id, structure_id, form_id)

    def mark_address_resolved(self, cur: Any, addr_id: int) -> None:
        mark_address_resolved(cur, addr_id)
