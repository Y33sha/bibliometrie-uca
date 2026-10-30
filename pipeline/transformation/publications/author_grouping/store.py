"""Requêtes de la phase `author_grouping`."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.persons.identifiers import AttributionStatus
from infrastructure.db.queues import Queue, delete_processed, enqueue, enqueue_sql, snapshot
from infrastructure.db.rows import rows_as
from infrastructure.sql_fragments import (
    in_clause,
    propagate_contribution_attributes_sql,
    usable_identifier,
)

# Statuts d'un rattachement d'identifiant posé par un humain.
_HUMAN_STATUSES = (AttributionStatus.CONFIRMED.value, AttributionStatus.AUTHENTICATED.value)

# Relevé de la file `publication_contributions_queue`, gardé d'un lot à l'autre : une table temporaire survit aux commits.
_SNAPSHOT = "publication_contributions_marks"

# Relevé de la file `contribution_attributes_queue`.
_ATTRIBUTES_SNAPSHOT = "contribution_attributes_marks"

# Marque les contributions des publications `:publications` pour la recomposition de leurs attributs.
_MARK_CONTRIBUTIONS_OF_PUBLICATIONS_SQL = text(
    enqueue_sql(
        Queue.CONTRIBUTION_ATTRIBUTES,
        "SELECT id FROM contributions WHERE publication_id = ANY(:publications)",
    )
)


def _known_first_name(id_type: str) -> str:
    """Renvoie l'expression SQL du prénom normalisé de la personne rattachée par un humain à l'identifiant `id_type` de la contribution source, s'il n'est pas neutralisé."""
    return f"""(
        SELECT p.first_name_normalized FROM person_identifiers pi JOIN persons p ON p.id = pi.person_id
        WHERE pi.id_type = '{id_type}' AND pi.id_value = {usable_identifier(f"'{id_type}'")}
          AND pi.status::text IN {in_clause(_HUMAN_STATUSES)}
    )"""


# Contributions sources à aligner, hors collectifs.
_SOURCE_CONTRIBUTIONS_SQL = text(f"""
    SELECT sr.publication_id, sr.id AS source_record, sr.source::text AS source,
           sc.id, sc.author_position AS position,
           ci.last_name_normalized AS last_name,
           coalesce(ci.first_name_normalized, '') AS first_name,
           coalesce({usable_identifier("'orcid'")}, '') AS orcid,
           coalesce({usable_identifier("'idref'")}, '') AS idref,
           coalesce({_known_first_name("orcid")}, {_known_first_name("idref")}, '') AS known_first_name
    FROM source_records sr
    JOIN source_contributions sc ON sc.source_record_id = sr.id
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
    WHERE sr.publication_id = ANY(:publications) AND NOT sc.collective
""")

_CONTRIBUTIONS_SQL = text("""
    SELECT g.id, g.publication_id, gs.source_contribution_id, gs.source_record_id,
           gs.method::text AS method, gs.score, gs.margin
    FROM contributions g
    LEFT JOIN aligned_source_contributions gs ON gs.contribution_id = g.id
    WHERE g.publication_id = ANY(:publications)
""")

_DELETE_MEMBERSHIPS_SQL = text(
    "DELETE FROM aligned_source_contributions WHERE source_contribution_id = ANY(:source_contributions)"
)

_DELETE_CONTRIBUTIONS_SQL = text("DELETE FROM contributions WHERE id = ANY(:ids)")

# Marque les contributions recomposées `:ids` rattachées à une personne, pour la redécision de leur personne.
_MARK_RECOMPOSED_SQL = text(
    enqueue_sql(
        Queue.CONTRIBUTION_RESOLUTION,
        "SELECT id FROM contributions WHERE id = ANY(:ids) AND person_id IS NOT NULL",
    )
)

_CLEAR_COPIES_SQL = text("""
    UPDATE source_contributions sc SET duplicate_of = NULL
    FROM source_records sr
    WHERE sc.source_record_id = sr.id AND sr.publication_id = ANY(:publications)
      AND sc.duplicate_of IS NOT NULL AND sc.id <> ALL(CAST(:copies AS integer[]))
""")

_SET_COPIES_SQL = text("""
    UPDATE source_contributions sc SET duplicate_of = u.original
    FROM unnest(CAST(:copies AS integer[]), CAST(:originals AS integer[])) AS u(id, original)
    WHERE sc.id = u.id AND sc.duplicate_of IS DISTINCT FROM u.original
""")

_UPDATE_POSITIONS_SQL = text("""
    UPDATE contributions g SET reference_position = u.position
    FROM unnest(CAST(:ids AS integer[]), CAST(:positions AS smallint[])) AS u(id, position)
    WHERE g.id = u.id
""")

_NEW_CONTRIBUTION_IDS_SQL = text(
    "SELECT nextval(pg_get_serial_sequence('publications.contributions', 'id'))"
    " FROM generate_series(1, :n)"
)

_INSERT_CONTRIBUTIONS_SQL = text("""
    INSERT INTO contributions (id, publication_id, reference_position)
    SELECT * FROM unnest(
        CAST(:ids AS integer[]), CAST(:publications AS integer[]), CAST(:positions AS smallint[]))
""")

_INSERT_MEMBERSHIPS_SQL = text("""
    INSERT INTO aligned_source_contributions
        (source_contribution_id, contribution_id, source_record_id, method, score, margin)
    SELECT * FROM unnest(
        CAST(:source_contributions AS integer[]), CAST(:contributions AS integer[]), CAST(:source_records AS integer[]),
        CAST(:methods AS grouping_method[]), CAST(:scores AS real[]), CAST(:margins AS real[]))
""")


@dataclass(frozen=True, slots=True)
class SourceContributionRow:
    """Contribution source à aligner, telle que la base la renvoie."""

    publication_id: int
    source_record: int
    source: str
    id: int
    position: int | None
    last_name: str
    first_name: str
    orcid: str
    idref: str
    known_first_name: str = ""


@dataclass(frozen=True, slots=True)
class ContributionRow:
    """Contribution à écrire."""

    id: int
    publication_id: int
    reference_position: int | None
    existing: bool
    """Vrai si l'identifiant est celui d'une contribution déjà en base."""


@dataclass(frozen=True, slots=True)
class MembershipRow:
    """Appartenance d'une contribution source à une contribution."""

    source_contribution: int
    contribution: int
    source_record: int
    method: str
    score: float | None
    margin: float | None


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """Écritures d'un lot de publications."""

    publication_ids: Sequence[int]
    contributions: list[ContributionRow]
    removed: list[int]
    """Contributions sources à appartenance en base supprimée."""
    memberships: list[MembershipRow]
    """Appartenances à insérer."""
    unmatched: list[int]
    """Contributions en base sans correspondant, à supprimer."""
    recomposed: list[int]
    """Contributions en base à contributions sources changées, marquées pour la redécision de leur personne par la phase `persons`."""
    copies: dict[int, int]
    """Doublon d'auteur → première occurrence de son nom (`duplicate_of`)."""


class AuthorGroupingStore:
    """Lectures et écritures des contributions."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def propagate_attributes(self) -> tuple[int, int]:
        """Recompose les attributs des contributions en file depuis leurs contributions sources (`propagate_contribution_attributes_sql`), puis supprime les marquages traités. Renvoie le nombre de contributions en file et le nombre de contributions mises à jour."""
        queue = Queue.CONTRIBUTION_ATTRIBUTES
        snapshot(self._conn, queue, _ATTRIBUTES_SNAPSHOT)
        queued = int(
            self._conn.execute(
                text(
                    f"SELECT count(*) FROM {_ATTRIBUTES_SNAPSHOT} t"  # noqa: S608
                    " JOIN contributions g ON g.id = t.id"
                )
            ).scalar_one()
        )
        updated = self._conn.execute(
            text(propagate_contribution_attributes_sql(f"SELECT id FROM {_ATTRIBUTES_SNAPSHOT}"))
        ).rowcount
        delete_processed(self._conn, queue, _ATTRIBUTES_SNAPSHOT)
        self._conn.execute(text(f"DROP TABLE {_ATTRIBUTES_SNAPSHOT}"))
        return queued, updated

    def refresh_alignment(self) -> None:
        """Rafraîchit `publication_author_alignment`, le recouvrement des listes d'auteurs de chaque publication."""
        self._conn.execute(
            text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_author_alignment")
        )

    def mark_all(self) -> int:
        """Marque toutes les publications pour l'alignement. Renvoie le nombre de publications marquées."""
        return enqueue(
            self._conn, Queue.PUBLICATION_CONTRIBUTIONS, "SELECT id FROM publications", {}
        )

    def snapshot_queued_publications(self) -> list[tuple[int, int]]:
        """Relève la file des publications à réaligner. Renvoie celles qui existent, avec le nombre de contributions sources d'auteur de leurs enregistrements sources (`author_count`)."""
        snapshot(self._conn, Queue.PUBLICATION_CONTRIBUTIONS, _SNAPSHOT)
        rows = self._conn.execute(
            text(f"""
                SELECT t.id, coalesce(sum(sr.author_count), 0)::integer AS source_contributions
                FROM {_SNAPSHOT} t
                JOIN publications p ON p.id = t.id
                LEFT JOIN source_records sr ON sr.publication_id = t.id
                GROUP BY t.id
                ORDER BY t.id
            """)  # noqa: S608
        ).all()
        return [(r.id, r.source_contributions) for r in rows]

    def delete_processed_marks(self, publication_ids: Sequence[int] | None = None) -> None:
        """Supprime de la file les marquages relevés de ces publications, ou tous les marquages relevés."""
        delete_processed(self._conn, Queue.PUBLICATION_CONTRIBUTIONS, _SNAPSHOT, publication_ids)

    def drop_snapshot(self) -> None:
        """Supprime le relevé de `snapshot_queued_publications`."""
        self._conn.execute(text(f"DROP TABLE {_SNAPSHOT}"))

    def fetch_source_contributions(
        self, publication_ids: Sequence[int]
    ) -> list[SourceContributionRow]:
        """Renvoie les contributions sources à aligner de ces publications."""
        rows = self._conn.execute(
            _SOURCE_CONTRIBUTIONS_SQL,
            {"publications": list(publication_ids)},
        )
        return rows_as(SourceContributionRow, rows)

    def fetch_contributions(
        self, publication_ids: Sequence[int]
    ) -> tuple[dict[int, dict[int, set[int]]], dict[int, MembershipRow]]:
        """Renvoie les contributions en base de ces publications (publication → contribution → contributions sources) et l'appartenance de chaque contribution source alignée."""
        contributions: dict[int, dict[int, set[int]]] = {}
        memberships: dict[int, MembershipRow] = {}
        for row in self._conn.execute(_CONTRIBUTIONS_SQL, {"publications": list(publication_ids)}):
            members = contributions.setdefault(row.publication_id, {}).setdefault(row.id, set())
            if row.source_contribution_id is not None:
                members.add(row.source_contribution_id)
                memberships[row.source_contribution_id] = MembershipRow(
                    row.source_contribution_id,
                    row.id,
                    row.source_record_id,
                    row.method,
                    row.score,
                    row.margin,
                )
        return contributions, memberships

    def new_contribution_ids(self, n: int) -> list[int]:
        """Tire `n` identifiants de la séquence des contributions."""
        if not n:
            return []
        return list(self._conn.execute(_NEW_CONTRIBUTION_IDS_SQL, {"n": n}).scalars())

    def write(self, plan: BatchPlan) -> None:
        """Écrit les contributions et les doublons d'auteur des publications du lot, et marque leurs contributions pour la recomposition de leurs attributs.

        Une contribution déjà en base garde son identifiant, sa personne et son mode de résolution. Une contribution à contributions sources changées est marquée pour la redécision de sa personne (`Queue.CONTRIBUTION_RESOLUTION`). Les autres contributions sources des publications du lot perdent leur `duplicate_of`.
        """
        publication_ids, contributions, removed = (
            plan.publication_ids,
            plan.contributions,
            plan.removed,
        )
        memberships, unmatched_ids, copies = plan.memberships, plan.unmatched, plan.copies
        self._conn.execute(
            _CLEAR_COPIES_SQL, {"publications": list(publication_ids), "copies": list(copies)}
        )
        if copies:
            self._conn.execute(
                _SET_COPIES_SQL, {"copies": list(copies), "originals": list(copies.values())}
            )
        if removed:
            self._conn.execute(_DELETE_MEMBERSHIPS_SQL, {"source_contributions": list(removed)})
        if unmatched_ids:
            self._conn.execute(_DELETE_CONTRIBUTIONS_SQL, {"ids": list(unmatched_ids)})
        if plan.recomposed:
            self._conn.execute(_MARK_RECOMPOSED_SQL, {"ids": list(plan.recomposed)})
        kept = [g for g in contributions if g.existing]
        if kept:
            self._conn.execute(
                _UPDATE_POSITIONS_SQL,
                {"ids": [g.id for g in kept], "positions": [g.reference_position for g in kept]},
            )
        created = [g for g in contributions if not g.existing]
        if created:
            self._conn.execute(
                _INSERT_CONTRIBUTIONS_SQL,
                {
                    "ids": [g.id for g in created],
                    "publications": [g.publication_id for g in created],
                    "positions": [g.reference_position for g in created],
                },
            )
        if memberships:
            self._conn.execute(
                _INSERT_MEMBERSHIPS_SQL,
                {
                    "source_contributions": [m.source_contribution for m in memberships],
                    "contributions": [m.contribution for m in memberships],
                    "source_records": [m.source_record for m in memberships],
                    "methods": [m.method for m in memberships],
                    "scores": [m.score for m in memberships],
                    "margins": [m.margin for m in memberships],
                },
            )
        self._conn.execute(
            _MARK_CONTRIBUTIONS_OF_PUBLICATIONS_SQL, {"publications": list(publication_ids)}
        )
