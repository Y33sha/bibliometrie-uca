"""Cycle de vie d'une publication : création, suppression après recalcul, dissolution, purge.

Une publication existe si elle a au moins un enregistrement source, un type admissible, et au moins une contribution rattachée à une personne ou un indice d'appartenance au périmètre lié au document (`DOCUMENT_EVIDENCE`). `refresh` vérifie les deux premières conditions après le recalcul des publications. `purge_publications` vérifie la première et la dernière sur toute la table, une fois les personnes résolues.
"""

from collections.abc import Callable, Sequence
from itertools import batched

from sqlalchemy import Connection, text

from domain.publications.oa_status import OaStatus
from infrastructure.db.queues import Queue, delete_processed, snapshot
from infrastructure.sql_fragments import has_document_evidence
from pipeline.transformation.publications.consolidation import RefreshVerdict, consolidate
from pipeline.transformation.publications.store import PublicationStore

_DELETION_VERDICTS = frozenset({RefreshVerdict.NO_SOURCE, RefreshVerdict.INADMISSIBLE_TYPE})

_REFRESH_BATCH_SIZE = 500
"""Publications recalculées ensemble : chaque lecture du recalcul porte sur un lot."""


def create(
    conn: Connection,
    *,
    title_normalized: str,
    doc_type: str | None,
    publication_year: int,
    doi: str | None,
) -> int:
    """Crée une publication avec les seules valeurs exigées par la table, et renvoie son id.

    Ces valeurs tiennent jusqu'au premier `refresh` : le titre est le titre normalisé, le type vaut `other` quand la source n'en donne aucun, le statut open access vaut la valeur par défaut.
    """
    return PublicationStore(conn).create(
        title=title_normalized,
        title_normalized=title_normalized,
        doc_type=doc_type or "other",
        publication_year=publication_year,
        doi=doi,
        oa_status=OaStatus.UNKNOWN,
    )


def refresh(
    conn: Connection,
    publication_ids: Sequence[int],
    *,
    on_batch: Callable[[int], None] | None = None,
) -> dict[int, RefreshVerdict]:
    """Recalcule les publications depuis leurs enregistrements sources, par lots (`consolidate`). Supprime celles sans enregistrement source ou de type inadmissible. Renvoie le verdict de chaque publication.

    Les suppressions d'un lot précèdent ses écritures : le DOI d'une publication supprimée passe ainsi à une publication du même lot.

    Args:
        on_batch: appelé après chaque lot, avec son nombre de publications.
    """
    store = PublicationStore(conn)
    verdicts: dict[int, RefreshVerdict] = {}
    for batch in batched(publication_ids, _REFRESH_BATCH_SIZE, strict=False):
        consolidation = consolidate(conn, batch)
        store.delete([p for p, v in consolidation.verdicts.items() if v in _DELETION_VERDICTS])
        store.save(consolidation.saved)
        verdicts.update(consolidation.verdicts)
        if on_batch is not None:
            on_batch(len(batch))
    return verdicts


_QUEUED = "publications_queue_marks"
"""Relevé de la file `publications_queue` par `refresh_queued`."""


def refresh_queued(conn: Connection, *, on_batch: Callable[[int], None] | None = None) -> int:
    """Recalcule les publications de la file `publications_queue` encore en base, puis supprime les marquages traités. Renvoie le nombre de publications recalculées."""
    snapshot(conn, Queue.PUBLICATIONS, _QUEUED)
    publication_ids = list(
        conn.execute(
            text(f"SELECT p.id FROM {_QUEUED} m JOIN publications p ON p.id = m.id ORDER BY p.id")  # noqa: S608
        ).scalars()
    )
    refresh(conn, publication_ids, on_batch=on_batch)
    delete_processed(conn, Queue.PUBLICATIONS, _QUEUED)
    return len(publication_ids)


def dissolve(conn: Connection, publication_id: int, successor_id: int) -> None:
    """Supprime une publication dont tous les enregistrements sources ont rejoint le successeur. Ses paiements APC passent au successeur, et son identifiant redirige vers lui.

    Raises:
        ValueError: un enregistrement source reste rattaché à la publication.
    """
    store = PublicationStore(conn)
    if store.has_source_records(publication_id):
        raise ValueError(
            f"Publication {publication_id} dissoute avec des source_records rattachées"
        )
    store.repoint_dependents(publication_id, successor_id)
    store.delete([publication_id])


def purge_publications(conn: Connection, *, limit: int | None = None) -> int:
    """Supprime les publications sans enregistrement source, ou sans contribution rattachée à une personne ni indice d'appartenance au périmètre lié au document (`DOCUMENT_EVIDENCE`), `limit` au plus. Renvoie le nombre de publications supprimées.

    Une publication perd son dernier enregistrement source quand la phase `normalize` retire un enregistrement source disparu de sa source. Elle perd sa dernière contribution rattachée à une personne par un rejet, une forme de nom rejetée ou une personne supprimée. Ses sujets sont supprimés avec elle (`ON DELETE CASCADE`).
    """
    limit_clause = "LIMIT :lim" if limit is not None else ""
    return conn.execute(
        text(f"""
            DELETE FROM publications
            WHERE id IN (
                SELECT p.id FROM publications p
                WHERE NOT EXISTS (SELECT 1 FROM source_records sr WHERE sr.publication_id = p.id)
                   OR (
                       NOT EXISTS (
                           SELECT 1 FROM contributions g
                           WHERE g.publication_id = p.id AND g.person_id IS NOT NULL
                       )
                       AND NOT {has_document_evidence("p.id")}
                   )
                {limit_clause}
            )
        """),
        {"lim": limit} if limit is not None else {},
    ).rowcount
