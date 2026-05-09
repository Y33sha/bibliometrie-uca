"""Opérations partagées sur `source_authorships` (cross-source).

Utilisé par les adapters de normalisation — la fonction est triviale
(un DELETE), mais on la garde ici pour éviter la duplication et
centraliser la sémantique.

Dispatche sur le type de `conn_or_cur` (psycopg | Connection SA),
le temps que tous les normalizers soient migrés en SA.
"""

from typing import Any

from sqlalchemy import Connection, text


def clear_source_authorships_for_publication(conn_or_cur: Any, source_publication_id: int) -> None:
    """Supprime toutes les ``source_authorships`` d'une ``source_publication``.

    Appelé en pré-normalisation pour que le re-traitement d'un document
    ne laisse pas de rows fantômes (auteurs retirés, positions abandonnées
    après un shift, etc.). ``source_publications.id`` étant unique pour
    un couple (source, source_id), seuls les authorships de la source
    concernée sont touchés.
    """
    if isinstance(conn_or_cur, Connection):
        conn_or_cur.execute(
            text("DELETE FROM source_authorships WHERE source_publication_id = :spid"),
            {"spid": source_publication_id},
        )
        return
    conn_or_cur.execute(
        "DELETE FROM source_authorships WHERE source_publication_id = %s",
        (source_publication_id,),
    )
