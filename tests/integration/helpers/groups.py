"""Groupes de signatures (`source_contribution_groups`, `source_contribution_group_members`) pour les tests d'intégration."""

from sqlalchemy import Connection, text


def insert_group(
    conn: Connection,
    publication_id: int,
    signatures: list[tuple[int, int]],
    *,
    method: str = "name",
) -> int:
    """Groupe les signatures `(signature, notice)` d'une publication et renvoie l'`id` du groupe. La première fonde le groupe ; les autres le rejoignent par `method`."""
    group_id = conn.execute(
        text("INSERT INTO source_contribution_groups (publication_id) VALUES (:p) RETURNING id"),
        {"p": publication_id},
    ).scalar_one()
    for rank, (signature, notice) in enumerate(signatures):
        conn.execute(
            text("""
                INSERT INTO source_contribution_group_members
                    (source_contribution_id, group_id, source_record_id, method)
                VALUES (:s, :g, :n, CAST(:m AS grouping_method))
            """),
            {"s": signature, "g": group_id, "n": notice, "m": "reference" if rank == 0 else method},
        )
    return group_id
