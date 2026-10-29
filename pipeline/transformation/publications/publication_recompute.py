"""Recalculs ciblés de publications après une fusion manuelle, exposés à l'API par `pipeline/public.py`."""

from collections.abc import Sequence

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import propagate_contribution_attributes_sql
from pipeline.transformation.publications.author_grouping.author_grouping import realign
from pipeline.transformation.publications.author_grouping.store import AuthorGroupingStore
from pipeline.transformation.publications.reconciliation import reconcile_source_records


class PublicationRecompute:
    """Réconciliation, alignement des auteurs et attributs des contributions de quelques publications."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def reconcile(self, source_record_ids: Sequence[int]) -> frozenset[int]:
        """Réconcilie le voisinage des enregistrements sources donnés et recalcule les métadonnées consolidées des publications conservées. Rend ces publications."""
        return reconcile_source_records(self._conn, source_record_ids).survivors

    def realign(self, publication_id: int) -> None:
        """Recalcule les contributions de la publication, puis leurs attributs : correspondant, rôles, indices de périmètre."""
        realign(AuthorGroupingStore(self._conn), [publication_id])
        self._conn.execute(
            text(
                propagate_contribution_attributes_sql(
                    "SELECT id FROM contributions WHERE publication_id = :publication"
                )
            ),
            {"publication": publication_id},
        )
