"""Query service : résolution des affiliations sur `source_authorships`, phase `affiliations`.

Appelé par `application/pipeline/affiliations/populate_affiliations.py` : rafraîchit la matview `source_authorship_structures`, puis pose `in_perimeter` depuis celle-ci.

Deux périmètres se composent. La matview est bornée au périmètre d'extraction, qu'elle lit par sa jointure sur `perimeter_structures` ; `sync_in_perimeter` la filtre ensuite sur les structures que l'appelant lui passe, celles du périmètre des personnes (`get_persons_structure_ids_list`).
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.affiliations.in_perimeter import (
    AffiliationsQueries,
    InPerimeterSyncCounts,
)

# Ensembles d'ids des deux UPDATE de `sync_in_perimeter` : `should` (authorships du périmètre restreint, via la matview) et `currently` (à TRUE, via l'index partiel). Delta par EXCEPT ; un run stable produit un delta vide.
_DELTA_CTE = """
    WITH should AS (
        SELECT DISTINCT source_authorship_id AS id
        FROM source_authorship_structures
        WHERE structure_id = ANY(:perimeter_ids)
    ),
    currently AS (
        SELECT id FROM source_authorships WHERE in_perimeter
    )
"""


def sync_in_perimeter(conn: Connection, *, perimeter_ids: list[int]) -> InPerimeterSyncCounts:
    """Aligne `in_perimeter` sur le périmètre, en n'écrivant que les changements.

    Dérivé de la matview `source_authorship_structures` (à rafraîchir en amont) : `in_perimeter = TRUE` ssi l'authorship y figure pour une structure du périmètre restreint. Delta par différence d'ensembles d'ids (index-only), pas de balayage des `source_authorships`.
    """
    params = {"perimeter_ids": perimeter_ids}
    added = conn.execute(
        text(
            _DELTA_CTE
            + """
            UPDATE source_authorships
            SET in_perimeter = TRUE
            WHERE id IN (SELECT id FROM should EXCEPT SELECT id FROM currently)
        """
        ),
        params,
    ).rowcount
    removed = conn.execute(
        text(
            _DELTA_CTE
            + """
            UPDATE source_authorships
            SET in_perimeter = FALSE
            WHERE id IN (SELECT id FROM currently EXCEPT SELECT id FROM should)
        """
        ),
        params,
    ).rowcount
    return InPerimeterSyncCounts(added=added, removed=removed)


def refresh_source_authorship_structures(conn: Connection) -> None:
    """Rafraîchit la matview `source_authorship_structures`, dérivée de `source_authorship_addresses ⋈ address_structures ⋈ perimeter_structures` et bornée au périmètre d'extraction (code lu dans la clé de config `perimeter_extraction`). `CONCURRENTLY` pour ne pas bloquer les lectures.

    À appeler après `perimeter_structures` et la résolution des adresses, avant le refresh de `authorship_structures` (matview-sur-matview).
    """
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY source_authorship_structures"))


class PgAffiliationsQueries(AffiliationsQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.affiliations.in_perimeter.AffiliationsQueries`."""

    def sync_in_perimeter(
        self, conn: Connection, *, perimeter_ids: list[int]
    ) -> InPerimeterSyncCounts:
        return sync_in_perimeter(conn, perimeter_ids=perimeter_ids)

    def refresh_source_authorship_structures(self, conn: Connection) -> None:
        refresh_source_authorship_structures(conn)
