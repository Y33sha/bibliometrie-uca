"""Semis des contributions (`contributions`, `aligned_source_contributions`), sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from sqlalchemy import Connection, text

from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.sql_fragments import propagate_contribution_attributes_sql
from tests.integration.helpers.queues import mark
from tests.integration.helpers.rows import perimeter_evidence

_MARK_UNGROUPED = enqueue_sql(
    Queue.CONTRIBUTION_ATTRIBUTES, "SELECT contribution_id FROM ungrouped"
)


def align_source_contributions(
    conn: Connection,
    publication_id: int,
    source_contributions: list[tuple[int, int]],
    *,
    method: str = "name",
) -> int:
    """Aligne dans une contribution les contributions sources `(contribution source, enregistrement source)` d'une publication, la marque pour la recomposition de ses attributs comme la phase `author_grouping`, et renvoie son `id`. La première contribution source fonde la contribution ; les autres la rejoignent par `method`."""
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


def add_aligned_source_contribution(
    conn: Connection, contribution_id: int, source_contribution_id: int, source_record_id: int
) -> None:
    """Ajoute la contribution source `source_contribution_id`, de l'enregistrement source `source_record_id`, à la contribution `contribution_id`."""
    conn.execute(
        text("""
            INSERT INTO aligned_source_contributions
                (source_contribution_id, contribution_id, source_record_id, method)
            VALUES (:s, :g, :n, 'name')
        """),
        {"s": source_contribution_id, "g": contribution_id, "n": source_record_id},
    )


def align_unaligned(conn: Connection) -> None:
    """Place dans sa propre contribution chaque contribution source non alignée d'un enregistrement source rattaché à une publication, hors collectifs et doublons d'auteur. La phase `author_grouping` traite ainsi un auteur sans correspondant dans les autres enregistrements sources. Marque les contributions créées pour la recomposition de leurs attributs."""
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


def recompose_contribution_attributes(conn: Connection) -> None:
    """Recompose les attributs de toutes les contributions depuis leurs contributions sources, comme la phase `author_grouping` pour les contributions en file."""
    conn.execute(text(propagate_contribution_attributes_sql("SELECT id FROM contributions")))


def contribution_of(conn: Connection, source_contribution_id: int) -> int:
    """Renvoie l'`id` de la contribution qui contient la contribution source `source_contribution_id`."""
    return conn.execute(
        text(
            "SELECT contribution_id FROM aligned_source_contributions"
            " WHERE source_contribution_id = :s"
        ),
        {"s": source_contribution_id},
    ).scalar_one()


def set_perimeter_author_contribution(
    conn: Connection, contribution_id: int, *, person_id: int | None = None, mode: str | None = None
) -> None:
    """Fait de la contribution `contribution_id` une contribution d'auteur du périmètre (rôle d'auteur, indice `address`), rattachée à la personne `person_id` par le mode de résolution `mode`."""
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


def insert_person_contribution(
    conn: Connection,
    source_contribution_id: int,
    *,
    person_id: int,
    mode: str = "name",
    in_perimeter: bool = True,
) -> int:
    """Place la contribution source `source_contribution_id` seule dans une contribution, et rattache cette contribution à la personne `person_id` par le mode de résolution `mode`. `in_perimeter` pose l'indice `address`. Renvoie l'`id` de la contribution."""
    row = conn.execute(
        text("""
            SELECT sc.source_record_id, sr.publication_id
            FROM source_contributions sc JOIN source_records sr ON sr.id = sc.source_record_id
            WHERE sc.id = :s
        """),
        {"s": source_contribution_id},
    ).one()
    contribution_id = align_source_contributions(
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


def contribution_person(conn: Connection, contribution_id: int) -> tuple[int | None, str | None]:
    """Renvoie la personne et le mode de résolution de la contribution `contribution_id`."""
    row = conn.execute(
        text("SELECT person_id, resolution_mode FROM contributions WHERE id = :g"),
        {"g": contribution_id},
    ).one()
    return row.person_id, row.resolution_mode
