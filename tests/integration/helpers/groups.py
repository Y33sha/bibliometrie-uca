"""Groupes de contributions sources (`source_contribution_groups`, `source_contribution_group_members`) pour les tests d'intégration."""

from sqlalchemy import Connection, text


def insert_group(
    conn: Connection,
    publication_id: int,
    source_contributions: list[tuple[int, int]],
    *,
    method: str = "name",
) -> int:
    """Groupe les contributions sources `(contribution source, enregistrement source)` d'une publication et renvoie l'`id` du groupe. La première fonde le groupe ; les autres le rejoignent par `method`."""
    group_id = conn.execute(
        text("INSERT INTO source_contribution_groups (publication_id) VALUES (:p) RETURNING id"),
        {"p": publication_id},
    ).scalar_one()
    for rank, (source_contribution, source_record) in enumerate(source_contributions):
        conn.execute(
            text("""
                INSERT INTO source_contribution_group_members
                    (source_contribution_id, group_id, source_record_id, method)
                VALUES (:s, :g, :n, CAST(:m AS grouping_method))
            """),
            {
                "s": source_contribution,
                "g": group_id,
                "n": source_record,
                "m": "reference" if rank == 0 else method,
            },
        )
    return group_id


def group_ungrouped(conn: Connection) -> None:
    """Donne un groupe à elle seule à chaque contribution source sans groupe d'un enregistrement source rattaché à une publication, hors collectifs et doublons d'auteur : le groupe que la phase `author_grouping` forme pour un auteur sans jumelle."""
    conn.execute(
        text("""
            WITH ungrouped AS (
                SELECT sc.id, sc.source_record_id, sr.publication_id,
                       nextval(pg_get_serial_sequence('publications.source_contribution_groups', 'id')) AS group_id
                FROM source_contributions sc
                JOIN source_records sr ON sr.id = sc.source_record_id
                WHERE sr.publication_id IS NOT NULL AND NOT sc.collective AND sc.duplicate_of IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM source_contribution_group_members gm
                      WHERE gm.source_contribution_id = sc.id)
            ), groups AS (
                INSERT INTO source_contribution_groups (id, publication_id)
                SELECT group_id, publication_id FROM ungrouped
            )
            INSERT INTO source_contribution_group_members
                (source_contribution_id, group_id, source_record_id, method)
            SELECT id, group_id, source_record_id, 'reference' FROM ungrouped
        """)
    )
