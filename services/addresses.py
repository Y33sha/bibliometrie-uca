"""
Service Addresses — accès exclusif en écriture aux tables `addresses`,
`address_structures`, et propagation des pays vers les publications.

Les routers passent par ces fonctions pour toute écriture sur les adresses.
Les lectures restent autorisées dans les routers (convention du projet).
"""

from psycopg2.extras import execute_values

from services.authorships import propagate_uca_for_addresses


# ── Validation des liens adresse ↔ structure ──────────────────────


def review_structure_link(cur, address_id: int, structure_id: int,
                           is_confirmed: bool | None):
    """Upsert le lien address ↔ structure (validation manuelle).

    - is_confirmed = True  → confirme (crée le lien si besoin)
    - is_confirmed = False → rejette (crée le lien si besoin)
    - is_confirmed = None  → reset (supprime le lien manuel, remet l'auto à NULL)

    Propage automatiquement l'UCA aux source_authorships et authorships vérité
    (via services.authorships.propagate_uca_for_addresses).
    """
    if is_confirmed is None:
        # Reset : retirer le lien manuel (sans matched_form_id), puis remettre
        # is_confirmed à NULL pour les liens auto-détectés restants.
        cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = %s AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_id, structure_id),
        )
        cur.execute(
            """
            UPDATE address_structures SET is_confirmed = NULL
            WHERE address_id = %s AND structure_id = %s
            """,
            (address_id, structure_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES (%s, %s, %s)
            ON CONFLICT (address_id, structure_id) DO UPDATE
                SET is_confirmed = EXCLUDED.is_confirmed
            """,
            (address_id, structure_id, is_confirmed),
        )

    propagate_uca_for_addresses(cur, [address_id])


def batch_review_structure_link(cur, address_ids: list[int], structure_id: int,
                                 is_confirmed: bool | None) -> int:
    """Comme review_structure_link mais sur un lot d'adresses.

    Retourne le nombre d'adresses touchées (pour les reset, nombre de lignes
    UPDATEes ; pour les upserts, taille du lot passé).
    """
    if not address_ids:
        return 0

    if is_confirmed is None:
        cur.execute(
            """
            DELETE FROM address_structures
            WHERE address_id = ANY(%s) AND structure_id = %s AND matched_form_id IS NULL
            """,
            (address_ids, structure_id),
        )
        cur.execute(
            """
            UPDATE address_structures SET is_confirmed = NULL
            WHERE address_id = ANY(%s) AND structure_id = %s
            """,
            (address_ids, structure_id),
        )
        updated = cur.rowcount
    else:
        execute_values(
            cur,
            """
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES %s
            ON CONFLICT (address_id, structure_id) DO UPDATE
                SET is_confirmed = EXCLUDED.is_confirmed
            """,
            [(aid, structure_id, is_confirmed) for aid in address_ids],
        )
        updated = len(address_ids)

    propagate_uca_for_addresses(cur, address_ids)
    return updated
