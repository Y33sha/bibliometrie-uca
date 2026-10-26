"""Groupes de contributions sources (`contributions`, `aligned_source_contributions`) pour les tests d'intégration."""

from sqlalchemy import Connection, text

from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.sql_fragments import propagate_contribution_attributes_sql
from tests.integration.helpers.queues import mark
from tests.integration.helpers.rows import perimeter_evidence

_MARK_UNGROUPED = enqueue_sql(
    Queue.CONTRIBUTION_ATTRIBUTES, "SELECT contribution_id FROM ungrouped"
)


def insert_group(
    conn: Connection,
    publication_id: int,
    source_contributions: list[tuple[int, int]],
    *,
    method: str = "name",
) -> int:
    """Groupe les contributions sources `(contribution source, enregistrement source)` d'une publication, marque le groupe pour la recomposition de ses attributs comme le groupement, et renvoie l'`id` du groupe. La première fonde le groupe ; les autres le rejoignent par `method`."""
    contribution_id = conn.execute(
        text("INSERT INTO contributions (publication_id) VALUES (:p) RETURNING id"),
        {"p": publication_id},
    ).scalar_one()
    for rank, (source_contribution, source_record) in enumerate(source_contributions):
        conn.execute(
            text("""
                INSERT INTO aligned_source_contributions
                    (source_contribution_id, contribution_id, source_record_id, method)
                VALUES (:s, :g, :n, CAST(:m AS grouping_method))
            """),
            {
                "s": source_contribution,
                "g": contribution_id,
                "n": source_record,
                "m": "reference" if rank == 0 else method,
            },
        )
    mark(conn, Queue.CONTRIBUTION_ATTRIBUTES, [contribution_id])
    return contribution_id


def add_group_member(
    conn: Connection, contribution_id: int, source_contribution_id: int, source_record_id: int
) -> None:
    """Ajoute la contribution source `source_contribution_id`, de l'enregistrement source `source_record_id`, au groupe `contribution_id`."""
    conn.execute(
        text("""
            INSERT INTO aligned_source_contributions
                (source_contribution_id, contribution_id, source_record_id, method)
            VALUES (:s, :g, :n, 'name')
        """),
        {"s": source_contribution_id, "g": contribution_id, "n": source_record_id},
    )


def group_ungrouped(conn: Connection) -> None:
    """Donne un groupe à elle seule à chaque contribution source sans groupe d'un enregistrement source rattaché à une publication, hors collectifs et doublons d'auteur : le groupe que la phase `author_grouping` forme pour un auteur sans jumelle. Les groupes créés sont marqués pour la recomposition de leurs attributs."""
    conn.execute(
        text(f"""
            WITH ungrouped AS (
                SELECT sc.id, sc.source_record_id, sr.publication_id,
                       nextval(pg_get_serial_sequence('publications.contributions', 'id')) AS contribution_id
                FROM source_contributions sc
                JOIN source_records sr ON sr.id = sc.source_record_id
                WHERE sr.publication_id IS NOT NULL AND NOT sc.collective AND sc.duplicate_of IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM aligned_source_contributions gm
                      WHERE gm.source_contribution_id = sc.id)
            ), groups AS (
                INSERT INTO contributions (id, publication_id)
                SELECT contribution_id, publication_id FROM ungrouped
            ), marked AS ({_MARK_UNGROUPED})
            INSERT INTO aligned_source_contributions
                (source_contribution_id, contribution_id, source_record_id, method)
            SELECT id, contribution_id, source_record_id, 'reference' FROM ungrouped
        """)
    )


def recompose_group_attributes(conn: Connection) -> None:
    """Recompose les attributs de tous les groupes depuis leurs membres, comme la phase `author_grouping` pour les groupes en file."""
    conn.execute(text(propagate_contribution_attributes_sql("SELECT id FROM contributions")))


def group_of(conn: Connection, source_contribution_id: int) -> int:
    """L'`id` du groupe de la contribution source `source_contribution_id`."""
    return conn.execute(
        text(
            "SELECT contribution_id FROM aligned_source_contributions"
            " WHERE source_contribution_id = :s"
        ),
        {"s": source_contribution_id},
    ).scalar_one()


def set_perimeter_author_group(
    conn: Connection, contribution_id: int, *, person_id: int | None = None, mode: str | None = None
) -> None:
    """Fait du groupe `contribution_id` un groupe d'auteur du périmètre (rôle d'auteur, indice `address`), rattaché à la personne `person_id` par le mode de résolution `mode`."""
    conn.execute(
        text("""
            UPDATE contributions
            SET person_id = :person,
                resolution_mode = CAST(:mode AS resolution_mode),
                roles = ARRAY['author'],
                perimeter_evidence = ARRAY['address']::perimeter_evidence[]
            WHERE id = :g
        """),
        {"g": contribution_id, "person": person_id, "mode": mode},
    )


def insert_person_group(
    conn: Connection,
    source_contribution_id: int,
    *,
    person_id: int,
    mode: str = "name",
    in_perimeter: bool = True,
) -> int:
    """Place la contribution source `source_contribution_id` seule dans un groupe, et rattache ce groupe à la personne `person_id` par le mode de résolution `mode`. `in_perimeter` pose l'indice `address`. Renvoie l'`id` du groupe."""
    row = conn.execute(
        text("""
            SELECT sc.source_record_id, sr.publication_id
            FROM source_contributions sc JOIN source_records sr ON sr.id = sc.source_record_id
            WHERE sc.id = :s
        """),
        {"s": source_contribution_id},
    ).one()
    contribution_id = insert_group(
        conn, row.publication_id, [(source_contribution_id, row.source_record_id)]
    )
    conn.execute(
        text("""
            UPDATE contributions
            SET person_id = :person,
                resolution_mode = CAST(:mode AS resolution_mode),
                perimeter_evidence = CAST(:evidence AS perimeter_evidence[])
            WHERE id = :g
        """),
        {
            "g": contribution_id,
            "person": person_id,
            "mode": mode,
            "evidence": perimeter_evidence(in_perimeter) or [],
        },
    )
    return contribution_id


def group_person(conn: Connection, contribution_id: int) -> tuple[int | None, str | None]:
    """Personne et mode de résolution du groupe `contribution_id`."""
    row = conn.execute(
        text("SELECT person_id, resolution_mode FROM contributions WHERE id = :g"),
        {"g": contribution_id},
    ).one()
    return row.person_id, row.resolution_mode
