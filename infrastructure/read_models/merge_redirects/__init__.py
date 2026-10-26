"""Lecture des redirections d'identifiants absorbés par une fusion (`merge_redirects`)."""

from sqlalchemy import Connection, text

from domain.merge import MergedEntity


class MergeRedirectQueries:
    """Redirection de l'identifiant d'une entité absorbée par une fusion."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def kept_id(self, entity: MergedEntity, absorbed_id: int) -> int | None:
        """Identifiant de l'entité conservée vers laquelle mène `absorbed_id`, ou `None` sans redirection."""
        return self._conn.execute(
            text("""
                SELECT kept_id FROM merge_redirects
                WHERE entity = CAST(:entity AS merged_entity) AND absorbed_id = :id
            """),
            {"entity": entity.value, "id": absorbed_id},
        ).scalar()
