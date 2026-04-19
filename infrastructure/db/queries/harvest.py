"""Query service : lectures et écritures pour les scripts de moissonnage HAL.

Appelé par `application/pipeline/harvest/*`. Regroupe le SQL de collecte des
identifiants (ORCID, IdRef) sur la table `source_persons`.
"""

from typing import Any

from infrastructure.db_helpers import rows_as_dicts


def fetch_hal_persons_missing_idref(cur: Any) -> list[dict[str, Any]]:
    """`source_persons` HAL avec `person_id` et sans `idref`.

    Retourne les colonnes utiles au script : `ha_id`, `hal_person_id`,
    `idhal`, `person_id`, `full_name` (dict rows pour lisibilité).
    """
    cur.execute("""
        SELECT sa.id AS ha_id,
               (sa.source_ids->>'hal_person_id')::int AS hal_person_id,
               sa.source_ids->>'idhal' AS idhal,
               sa.person_id, sa.full_name
        FROM source_persons sa
        WHERE sa.source = 'hal'
          AND (sa.source_ids->>'hal_person_id') IS NOT NULL
          AND sa.person_id IS NOT NULL
          AND sa.idref IS NULL
        ORDER BY sa.person_id
    """)
    return rows_as_dicts(cur)


def fetch_hal_persons_missing_identifiers(cur: Any) -> list[tuple[int, int, int | None]]:
    """`source_persons` HAL avec `hal_person_id` et ORCID ou IdRef manquant.

    Retourne `(source_person_id, hal_person_id, person_id)` pour la boucle
    de moissonnage batch (ORCID + IdRef en une passe).
    """
    cur.execute("""
        SELECT id, (source_ids->>'hal_person_id')::int AS hal_person_id, person_id
        FROM source_persons
        WHERE source = 'hal'
          AND (source_ids->>'hal_person_id') IS NOT NULL
          AND (orcid IS NULL OR idref IS NULL)
        ORDER BY id
    """)
    return cur.fetchall()


def update_source_person_idref(cur: Any, source_person_id: int, idref: str) -> None:
    """Écrase `source_persons.idref` pour l'id donné (pas de protection NULL)."""
    cur.execute(
        "UPDATE source_persons SET idref = %s WHERE id = %s",
        (idref, source_person_id),
    )


def fill_source_person_orcid_if_null(cur: Any, source_person_id: int, orcid: str) -> bool:
    """Renseigne `orcid` seulement si NULL. Retourne True si une ligne a été modifiée."""
    cur.execute(
        """
        UPDATE source_persons
        SET orcid = COALESCE(orcid, %s), updated_at = now()
        WHERE id = %s AND orcid IS NULL
        """,
        (orcid, source_person_id),
    )
    return cur.rowcount > 0


def fill_source_person_idref_if_null(cur: Any, source_person_id: int, idref: str) -> bool:
    """Renseigne `idref` seulement si NULL. Retourne True si une ligne a été modifiée."""
    cur.execute(
        """
        UPDATE source_persons
        SET idref = COALESCE(idref, %s), updated_at = now()
        WHERE id = %s AND idref IS NULL
        """,
        (idref, source_person_id),
    )
    return cur.rowcount > 0
