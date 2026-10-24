"""Groupes de contributions sources (`source_contribution_groups`, `source_contribution_group_members`) pour les tests d'intégration."""

from sqlalchemy import Connection, text

from infrastructure.db.queues import Queue, enqueue_sql
from tests.integration.helpers.queues import mark

_MARK_UNGROUPED = enqueue_sql(
    Queue.SOURCE_CONTRIBUTION_GROUP_ATTRIBUTES, "SELECT group_id FROM ungrouped"
)


def insert_group(
    conn: Connection,
    publication_id: int,
    source_contributions: list[tuple[int, int]],
    *,
    method: str = "name",
) -> int:
    """Groupe les contributions sources `(contribution source, enregistrement source)` d'une publication, marque le groupe pour la recomposition de ses attributs comme le groupement, et renvoie l'`id` du groupe. La première fonde le groupe ; les autres le rejoignent par `method`."""
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
    mark(conn, Queue.SOURCE_CONTRIBUTION_GROUP_ATTRIBUTES, [group_id])
    return group_id


def add_group_member(
    conn: Connection, group_id: int, source_contribution_id: int, source_record_id: int
) -> None:
    """Ajoute la contribution source `source_contribution_id`, de l'enregistrement source `source_record_id`, au groupe `group_id`."""
    conn.execute(
        text("""
            INSERT INTO source_contribution_group_members
                (source_contribution_id, group_id, source_record_id, method)
            VALUES (:s, :g, :n, 'name')
        """),
        {"s": source_contribution_id, "g": group_id, "n": source_record_id},
    )


def group_ungrouped(conn: Connection) -> None:
    """Donne un groupe à elle seule à chaque contribution source sans groupe d'un enregistrement source rattaché à une publication, hors collectifs et doublons d'auteur : le groupe que la phase `author_grouping` forme pour un auteur sans jumelle. Les groupes créés sont marqués pour la recomposition de leurs attributs."""
    conn.execute(
        text(f"""
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
            ), marked AS ({_MARK_UNGROUPED})
            INSERT INTO source_contribution_group_members
                (source_contribution_id, group_id, source_record_id, method)
            SELECT id, group_id, source_record_id, 'reference' FROM ungrouped
        """)
    )
