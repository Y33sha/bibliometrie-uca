"""Lecture des redirections d'identifiants absorbés par une fusion (`merge_redirects`)."""

from sqlalchemy import Connection, text

from application.ports.read_models.merge_redirects_queries import MergeRedirectQueries
from domain.merge import MergedEntity


class PgMergeRedirectQueries(MergeRedirectQueries):
    """Adapter SA pour `application.ports.read_models.merge_redirects_queries.MergeRedirectQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def kept_id(self, entity: MergedEntity, absorbed_id: int) -> int | None:
        return self._conn.execute(
            text("""
                SELECT kept_id FROM merge_redirects
                WHERE entity = CAST(:entity AS merged_entity) AND absorbed_id = :id
            """),
            {"entity": entity.value, "id": absorbed_id},
        ).scalar()
