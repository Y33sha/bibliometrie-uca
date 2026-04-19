"""Query service : lectures pour les scripts de fusion cross-source.

Appelé par `application/pipeline/merge/*`. Les scripts détectent des
publications distinctes qui référencent le même document (via NNT ou
identifiant HAL) et les fusionnent. Les fusions métier elles-mêmes
passent par `application.publications.merge_publications`.
"""

from typing import Any

from infrastructure.db_helpers import rows_as_dicts


def find_nnt_duplicates(cur: Any) -> list[dict[str, Any]]:
    """Liste les NNT dont les `source_publications` pointent vers plusieurs publications.

    Retourne des dicts `{nnt, pub_ids, sources}`.
    """
    cur.execute("""
        SELECT sd.external_ids->>'nnt' AS nnt,
               array_agg(DISTINCT sd.publication_id ORDER BY sd.publication_id) AS pub_ids,
               array_agg(DISTINCT sd.source::text ORDER BY sd.source::text) AS sources
        FROM source_publications sd
        WHERE sd.external_ids->>'nnt' IS NOT NULL
          AND sd.publication_id IS NOT NULL
        GROUP BY sd.external_ids->>'nnt'
        HAVING COUNT(DISTINCT sd.publication_id) > 1
        ORDER BY sd.external_ids->>'nnt'
    """)
    return rows_as_dicts(cur)


def rank_publications_by_merge_priority(
    cur: Any, publication_ids: list[int]
) -> list[dict[str, Any]]:
    """Classe des publications par ordre de préférence pour la fusion.

    Priorité : DOI (shape `10.*`) > nombre de `source_publications` > id le plus bas.
    La première de la liste retournée doit être conservée ; les suivantes sont
    à fusionner dedans.
    """
    cur.execute(
        """
        SELECT p.id, p.doi,
               (SELECT COUNT(*) FROM source_publications sd
                WHERE sd.publication_id = p.id) AS sd_count
        FROM publications p
        WHERE p.id = ANY(%s)
        ORDER BY
            (p.doi IS NOT NULL AND p.doi ~ '^10\\.') DESC,
            (SELECT COUNT(*) FROM source_publications sd
             WHERE sd.publication_id = p.id) DESC,
            p.id ASC
        """,
        (publication_ids,),
    )
    return rows_as_dicts(cur)


def fetch_source_publications_with_hal_external_id(
    cur: Any,
) -> list[dict[str, Any]]:
    """`source_publications` OpenAlex/ScanR qui référencent un `external_ids.hal`.

    Retourne `{src_doc_id, source, src_id, src_pub_id, hal_id}` pour chaque ligne.
    """
    cur.execute("""
        SELECT sd.id AS src_doc_id, sd.source::text AS source,
               sd.source_id AS src_id, sd.publication_id AS src_pub_id,
               sd.external_ids->>'hal' AS hal_id
        FROM source_publications sd
        WHERE sd.source IN ('openalex', 'scanr')
          AND sd.external_ids->>'hal' IS NOT NULL
    """)
    return rows_as_dicts(cur)


def fetch_hal_source_publications(cur: Any) -> list[dict[str, Any]]:
    """`source_publications` HAL avec leur identifiant HAL et leur `publication_id`."""
    cur.execute(
        """
        SELECT id AS hal_doc_id, source_id AS halid, publication_id AS hal_pub_id
        FROM source_publications
        WHERE source = 'hal'
        """
    )
    return rows_as_dicts(cur)


def link_source_publication_to_publication(
    cur: Any, source_publication_id: int, publication_id: int
) -> None:
    """Assigne `publication_id` à un `source_publications` donné."""
    cur.execute(
        "UPDATE source_publications SET publication_id = %s WHERE id = %s",
        (publication_id, source_publication_id),
    )
