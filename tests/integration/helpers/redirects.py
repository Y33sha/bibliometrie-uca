"""Lecture des redirections d'identifiants absorbés par une fusion."""

from sqlalchemy import Connection, text

from domain.merge import MergedEntity


def redirect_of(conn: Connection, entity: MergedEntity, absorbed_id: int) -> int | None:
    """Renvoie l'identifiant conservé vers lequel mène `absorbed_id`, ou `None` sans redirection."""
    return conn.execute(
        text("""
            SELECT kept_id FROM merge_redirects
            WHERE entity = CAST(:entity AS merged_entity) AND absorbed_id = :id
        """),
        {"entity": entity.value, "id": absorbed_id},
    ).scalar()
