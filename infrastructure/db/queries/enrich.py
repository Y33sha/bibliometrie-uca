"""Query service : lectures pour les scripts d'enrichissement pipeline.

Appelé par `application/pipeline/enrich/*`. Chaque fonction renvoie la liste
des publications/revues à traiter par le script d'enrichissement.
"""

from typing import Any


def fetch_publications_with_doi(
    cur: Any, *, limit: int | None = None
) -> list[tuple[int, str, str | None]]:
    """Liste `(id, doi, oa_status)` des publications avec un DOI.

    Utilisé par `enrich_oa_status` pour interroger Unpaywall. Tri par
    `pub_year DESC, id` pour traiter les publications récentes en premier.
    """
    if limit and limit > 0:
        cur.execute(
            """
            SELECT id, doi, oa_status::text
            FROM publications
            WHERE doi IS NOT NULL
            ORDER BY pub_year DESC, id
            LIMIT %s
            """,
            (limit,),
        )
    else:
        cur.execute(
            """
            SELECT id, doi, oa_status::text
            FROM publications
            WHERE doi IS NOT NULL
            ORDER BY pub_year DESC, id
            """
        )
    return cur.fetchall()


def fetch_journals_needing_apc(cur: Any, *, limit: int | None = None) -> list[tuple[int, str]]:
    """Liste `(id, openalex_id)` des revues à enrichir côté APC/DOAJ.

    Utilisé par `enrich_journal_apc`. Filtre les revues avec un
    `openalex_id` et sans `apc_amount` renseigné.
    """
    if limit and limit > 0:
        cur.execute(
            """
            SELECT id, openalex_id
            FROM journals
            WHERE openalex_id IS NOT NULL
              AND apc_amount IS NULL
            ORDER BY id
            LIMIT %s
            """,
            (limit,),
        )
    else:
        cur.execute(
            """
            SELECT id, openalex_id
            FROM journals
            WHERE openalex_id IS NOT NULL
              AND apc_amount IS NULL
            ORDER BY id
            """
        )
    return cur.fetchall()
