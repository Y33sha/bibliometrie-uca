"""Accès aux personnes et aux signatures que plusieurs tâches de la phase `persons` partagent."""

from sqlalchemy import Connection, text

from domain.persons.matching import (
    Namesake,
)
from infrastructure.sql_fragments import (
    DETACHED_SIGNATURE,
    pinned,
)


class PersonsStore:
    """Requêtes partagées de la phase `persons`, sur la connexion de la transaction."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def namesakes(self) -> list[Namesake]:
        """Les personnes non exclues, avec leur nom et prénom tels que saisis — matière du rattachement par initiales compatibles."""
        rows = self._conn.execute(
            text("""
                SELECT id, last_name, COALESCE(first_name, '') AS first_name
                FROM persons
                WHERE exclusion IS NULL
                ORDER BY id
            """)
        ).all()
        return [Namesake(r.id, r.last_name, r.first_name) for r in rows]

    def detach_signatures(self, source_authorship_ids: list[int]) -> int:
        """Sert aux liens cross-source devenus sans appui : une signature dont l'ancre ferme a disparu ce run et que la cascade n'a pas re-résolue."""
        if not source_authorship_ids:
            return 0
        return self._conn.execute(
            text(f"""
                UPDATE source_authorships sa
                SET {DETACHED_SIGNATURE}
                WHERE sa.id = ANY(:ids) AND NOT {pinned("sa.id")}
            """),
            {"ids": source_authorship_ids},
        ).rowcount
