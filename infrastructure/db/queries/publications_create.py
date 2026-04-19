"""Query service : SQL du script `create_publications`.

Appelé par `application/pipeline/create/create_publications.py`. Sélectionne
les `source_publications` in-perimeter orphelins (sans `publication_id`)
pour la création de l'entité consolidée `publications`.

L'attachement d'un `source_publications` à un `publications` est mutualisé
avec le script de fusion (voir `queries.merge.link_source_publication_to_publication`).
"""

from typing import Any

from infrastructure.db_helpers import rows_as_dicts


def fetch_orphan_in_perimeter_source_publications(cur: Any) -> list[dict[str, Any]]:
    """`source_publications` sans `publication_id` ayant au moins un
    `source_authorship` in_perimeter.

    Retourne les colonnes nécessaires pour la recherche/création de l'entité
    `publications` consolidée.
    """
    cur.execute("""
        SELECT sd.id, sd.source, sd.source_id, sd.doi, sd.title, sd.pub_year,
               sd.doc_type, sd.journal_id, sd.oa_status, sd.language,
               sd.container_title, sd.external_ids,
               sd.is_retracted, sd.biblio, sd.abstract, sd.keywords, sd.topics
        FROM source_publications sd
        WHERE sd.publication_id IS NULL
          AND EXISTS (
              SELECT 1 FROM source_authorships sa
              WHERE sa.source_publication_id = sd.id AND sa.in_perimeter = TRUE
          )
        ORDER BY sd.id
    """)
    return rows_as_dicts(cur)
