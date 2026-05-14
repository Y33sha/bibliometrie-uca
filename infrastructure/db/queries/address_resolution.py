"""Query service : SQL du pipeline de résolution d'adresses.

Appelé par `application/pipeline/addresses/resolve_addresses.py`.
Regroupe les opérations SQL de la boucle de matching adresses → structures
(détection automatique via `structure_name_forms`).

Séparé de `infrastructure/db/queries/addresses.py`, qui sert la couche API
(lecture/CRUD des adresses). Ici : écritures de la pipeline.
"""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.pipeline.address_resolution import AddressResolutionQueries


def load_name_forms(conn: Connection) -> list[dict[str, Any]]:
    """Charge toutes les formes depuis `structure_name_forms` + infos structure."""
    rows = conn.execute(
        text("""
            SELECT nf.id, nf.structure_id, nf.form_text,
                   nf.is_word_boundary, nf.requires_context_of,
                   nf.is_excluding,
                   s.code AS struct_code, s.structure_type::text AS struct_type
            FROM structure_name_forms nf
            JOIN structures s ON s.id = nf.structure_id
            ORDER BY nf.id
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def reset_auto_detected(conn: Connection) -> int:
    """Supprime les liens `address_structures` auto-détectés. Retourne le rowcount."""
    return conn.execute(
        text("DELETE FROM address_structures WHERE matched_form_id IS NOT NULL")
    ).rowcount


def reset_all_resolved_at(conn: Connection) -> None:
    """Remet `addresses.resolved_at` à NULL pour forcer un recalcul complet."""
    conn.execute(text("UPDATE addresses SET resolved_at = NULL"))


def fetch_addresses_to_resolve(conn: Connection, *, incremental: bool) -> list[tuple[int, str]]:
    """Retourne `(id, raw_text)` des adresses à traiter.

    Si `incremental=True` : uniquement celles avec `resolved_at IS NULL`.
    Sinon : toutes les adresses.
    """
    if incremental:
        rows = conn.execute(
            text(
                "SELECT a.id, a.raw_text FROM addresses a WHERE a.resolved_at IS NULL ORDER BY a.id"
            )
        ).all()
    else:
        rows = conn.execute(text("SELECT a.id, a.raw_text FROM addresses a ORDER BY a.id")).all()
    return [(r.id, r.raw_text) for r in rows]


def delete_obsolete_detections(
    conn: Connection, addr_id: int, kept_structure_ids: list[int]
) -> int:
    """Supprime les liens auto-détectés devenus obsolètes (non confirmés).

    `kept_structure_ids` : structures toujours détectées (à garder).
    Les liens `matched_form_id IS NOT NULL` vers d'autres structures et
    `is_confirmed IS NULL` sont supprimés. Retourne le rowcount.
    """
    if kept_structure_ids:
        return conn.execute(
            text("""
                DELETE FROM address_structures
                WHERE address_id = :addr_id
                  AND matched_form_id IS NOT NULL
                  AND structure_id != ALL(:kept)
                  AND is_confirmed IS NULL
            """),
            {"addr_id": addr_id, "kept": kept_structure_ids},
        ).rowcount
    return conn.execute(
        text("""
            DELETE FROM address_structures
            WHERE address_id = :addr_id
              AND matched_form_id IS NOT NULL
              AND is_confirmed IS NULL
        """),
        {"addr_id": addr_id},
    ).rowcount


def unflag_obsolete_detections(
    conn: Connection, addr_id: int, kept_structure_ids: list[int]
) -> None:
    """Retire `matched_form_id` sur les liens obsolètes confirmés/rejetés manuellement.

    Les liens manuels (is_confirmed IS NOT NULL) ne sont pas supprimés,
    mais perdent leur marqueur de détection auto.
    """
    if kept_structure_ids:
        conn.execute(
            text("""
                UPDATE address_structures
                SET matched_form_id = NULL
                WHERE address_id = :addr_id
                  AND matched_form_id IS NOT NULL
                  AND structure_id != ALL(:kept)
                  AND is_confirmed IS NOT NULL
            """),
            {"addr_id": addr_id, "kept": kept_structure_ids},
        )
    else:
        conn.execute(
            text("""
                UPDATE address_structures
                SET matched_form_id = NULL
                WHERE address_id = :addr_id
                  AND matched_form_id IS NOT NULL
                  AND is_confirmed IS NOT NULL
            """),
            {"addr_id": addr_id},
        )


def upsert_detected_structure(
    conn: Connection, addr_id: int, structure_id: int, form_id: int
) -> None:
    """Crée ou met à jour le lien `address_structures` avec le form_id détecté."""
    conn.execute(
        text("""
            INSERT INTO address_structures
                (address_id, structure_id, matched_form_id)
            VALUES (:addr_id, :struct_id, :form_id)
            ON CONFLICT (address_id, structure_id)
                DO UPDATE SET matched_form_id = EXCLUDED.matched_form_id
        """),
        {"addr_id": addr_id, "struct_id": structure_id, "form_id": form_id},
    )


def mark_address_resolved(conn: Connection, addr_id: int) -> None:
    """Marque une adresse comme résolue (`resolved_at = now()`)."""
    conn.execute(
        text("UPDATE addresses SET resolved_at = now() WHERE id = :addr_id"),
        {"addr_id": addr_id},
    )


class PgAddressResolutionQueries(AddressResolutionQueries):
    """Adapter PostgreSQL pour `application.ports.address_resolution.AddressResolutionQueries`."""

    def load_name_forms(self, conn: Connection) -> list[dict[str, Any]]:
        return load_name_forms(conn)

    def reset_auto_detected(self, conn: Connection) -> int:
        return reset_auto_detected(conn)

    def reset_all_resolved_at(self, conn: Connection) -> None:
        reset_all_resolved_at(conn)

    def fetch_addresses_to_resolve(
        self, conn: Connection, *, incremental: bool
    ) -> list[tuple[int, str]]:
        return fetch_addresses_to_resolve(conn, incremental=incremental)

    def delete_obsolete_detections(
        self, conn: Connection, addr_id: int, kept_structure_ids: list[int]
    ) -> int:
        return delete_obsolete_detections(conn, addr_id, kept_structure_ids)

    def unflag_obsolete_detections(
        self, conn: Connection, addr_id: int, kept_structure_ids: list[int]
    ) -> None:
        unflag_obsolete_detections(conn, addr_id, kept_structure_ids)

    def upsert_detected_structure(
        self, conn: Connection, addr_id: int, structure_id: int, form_id: int
    ) -> None:
        upsert_detected_structure(conn, addr_id, structure_id, form_id)

    def mark_address_resolved(self, conn: Connection, addr_id: int) -> None:
        mark_address_resolved(conn, addr_id)
