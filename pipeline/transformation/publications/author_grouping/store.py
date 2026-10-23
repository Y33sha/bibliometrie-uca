"""Requêtes de la phase `author_grouping`."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.persons.identifiers import AttributionStatus
from domain.publications.author_grouping import REPEATED_LIST_CASES
from infrastructure.db.queues import Queue, delete_processed, enqueue, snapshot
from infrastructure.db.rows import rows_as
from infrastructure.sql_fragments import (
    corrected_by,
    in_clause,
    propagate_group_attributes_sql,
    usable_identifier,
)

# Statuts d'un rattachement d'identifiant posé par un humain.
_HUMAN_STATUSES = (AttributionStatus.CONFIRMED.value, AttributionStatus.AUTHENTICATED.value)

# Relevé de la file `publication_contributions_queue`, gardé d'un lot à l'autre : une table temporaire survit aux commits.
_SNAPSHOT = "publication_contributions_marks"


def _known_first_name(id_type: str) -> str:
    """Prénom normalisé de la personne à laquelle un humain a rattaché l'identifiant `id_type` de la contribution source `sa`, s'il n'est pas neutralisé."""
    return f"""(
        SELECT p.first_name_normalized FROM person_identifiers pi JOIN persons p ON p.id = pi.person_id
        WHERE pi.id_type = '{id_type}' AND pi.id_value = {usable_identifier(f"'{id_type}'")}
          AND pi.status::text IN {in_clause(_HUMAN_STATUSES)}
    )"""


# Contributions sources à grouper, hors collectifs, hors enregistrements sources à liste répétée (`REPEATED_LIST_CASES`).
_SOURCE_CONTRIBUTIONS_SQL = text(f"""
    WITH records AS (
        SELECT sr.id, sr.publication_id, sr.source::text AS source,
               ({corrected_by("doi")}) = ANY(:repeated) IS TRUE AS repeated
        FROM source_records sr
        WHERE sr.publication_id = ANY(:publications)
    ), kept AS (
        SELECT n.* FROM records n
        WHERE NOT (n.repeated AND EXISTS (
                SELECT 1 FROM records o WHERE o.publication_id = n.publication_id AND NOT o.repeated))
    )
    SELECT k.publication_id, k.id AS source_record, k.source, sc.id, sc.author_position AS position,
           ci.last_name_normalized AS last_name,
           coalesce(ci.first_name_normalized, '') AS first_name,
           coalesce({usable_identifier("'orcid'")}, '') AS orcid,
           coalesce({usable_identifier("'idref'")}, '') AS idref,
           coalesce({_known_first_name("orcid")}, {_known_first_name("idref")}, '') AS known_first_name
    FROM kept k
    JOIN source_contributions sc ON sc.source_record_id = k.id
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
    WHERE NOT sc.collective
""")

_GROUPS_SQL = text("""
    SELECT g.id, g.publication_id, gs.source_contribution_id, gs.source_record_id,
           gs.method::text AS method, gs.score, gs.margin
    FROM source_contribution_groups g
    LEFT JOIN source_contribution_group_members gs ON gs.group_id = g.id
    WHERE g.publication_id = ANY(:publications)
""")

_DELETE_MEMBERSHIPS_SQL = text(
    "DELETE FROM source_contribution_group_members WHERE source_contribution_id = ANY(:source_contributions)"
)

_DELETE_GROUPS_SQL = text("DELETE FROM source_contribution_groups WHERE id = ANY(:ids)")

_DETACH_GROUPS_SQL = text(
    "UPDATE source_contribution_groups SET person_id = NULL, resolution_mode = NULL"
    " WHERE id = ANY(:ids) AND person_id IS NOT NULL"
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
    UPDATE source_contribution_groups g SET reference_position = u.position
    FROM unnest(CAST(:ids AS integer[]), CAST(:positions AS smallint[])) AS u(id, position)
    WHERE g.id = u.id
""")

_GROUP_IDS_SQL = text(
    "SELECT nextval(pg_get_serial_sequence('publications.source_contribution_groups', 'id'))"
    " FROM generate_series(1, :n)"
)

_INSERT_GROUPS_SQL = text("""
    INSERT INTO source_contribution_groups (id, publication_id, reference_position)
    SELECT * FROM unnest(
        CAST(:ids AS integer[]), CAST(:publications AS integer[]), CAST(:positions AS smallint[]))
""")

_INSERT_MEMBERSHIPS_SQL = text("""
    INSERT INTO source_contribution_group_members
        (source_contribution_id, group_id, source_record_id, method, score, margin)
    SELECT * FROM unnest(
        CAST(:source_contributions AS integer[]), CAST(:groups AS integer[]), CAST(:source_records AS integer[]),
        CAST(:methods AS grouping_method[]), CAST(:scores AS real[]), CAST(:margins AS real[]))
""")


@dataclass(frozen=True, slots=True)
class SourceContributionRow:
    """Contribution source à grouper, telle que la base la rend."""

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
class GroupRow:
    """Groupe à écrire. `existing` : l'identifiant est celui d'un groupe déjà en base."""

    id: int
    publication_id: int
    reference_position: int | None
    existing: bool


@dataclass(frozen=True, slots=True)
class MembershipRow:
    """Appartenance d'une contribution source à un groupe."""

    source_contribution: int
    group: int
    source_record: int
    method: str
    score: float | None
    margin: float | None


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """Écritures d'un lot de publications."""

    publication_ids: Sequence[int]
    groups: list[GroupRow]
    removed: list[int]
    """Contributions sources dont l'appartenance en base est supprimée."""
    memberships: list[MembershipRow]
    """Appartenances à insérer."""
    unmatched: list[int]
    """Groupes en base sans correspondant, supprimés."""
    recomposed: list[int]
    """Groupes en base dont les membres changent : ils perdent leur personne, que la phase `persons` redécide."""
    copies: dict[int, int]
    """Doublon d'auteur → première occurrence de son nom (`duplicate_of`)."""


class SourceContributionGroupStore:
    """Lectures et écritures des groupes de contributions sources."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def propagate_attributes(self) -> int:
        """Recompose les attributs de tous les groupes depuis leurs membres (`propagate_group_attributes_sql`). Rend le nombre de groupes réécrits."""
        return self._conn.execute(text(propagate_group_attributes_sql())).rowcount

    def refresh_alignment(self) -> None:
        """Rafraîchit `publication_author_alignment`, le recouvrement des listes d'auteurs de chaque publication."""
        self._conn.execute(
            text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_author_alignment")
        )

    def mark_all(self) -> int:
        """Marque toutes les publications pour le groupement. Rend le nombre de publications marquées."""
        return enqueue(
            self._conn, Queue.PUBLICATION_CONTRIBUTIONS, "SELECT id FROM publications", {}
        )

    def snapshot_queued_publications(self) -> list[tuple[int, int]]:
        """Relève la file des publications à regrouper. Rend ces publications, avec le nombre de contributions sources d'auteur de leurs enregistrements sources (`author_count`)."""
        snapshot(self._conn, Queue.PUBLICATION_CONTRIBUTIONS, _SNAPSHOT)
        rows = self._conn.execute(
            text(f"""
                SELECT t.id, coalesce(sum(sr.author_count), 0)::integer AS source_contributions
                FROM {_SNAPSHOT} t
                LEFT JOIN source_records sr ON sr.publication_id = t.id
                GROUP BY t.id
                ORDER BY t.id
            """)  # noqa: S608
        ).all()
        return [(r.id, r.source_contributions) for r in rows]

    def delete_processed_marks(self, publication_ids: Sequence[int]) -> None:
        """Supprime de la file les marquages relevés de ces publications."""
        delete_processed(self._conn, Queue.PUBLICATION_CONTRIBUTIONS, _SNAPSHOT, publication_ids)

    def drop_snapshot(self) -> None:
        """Supprime le relevé de `snapshot_queued_publications`."""
        self._conn.execute(text(f"DROP TABLE {_SNAPSHOT}"))

    def fetch_source_contributions(
        self, publication_ids: Sequence[int]
    ) -> list[SourceContributionRow]:
        """Contributions sources à grouper de ces publications."""
        rows = self._conn.execute(
            _SOURCE_CONTRIBUTIONS_SQL,
            {"publications": list(publication_ids), "repeated": list(REPEATED_LIST_CASES)},
        )
        return rows_as(SourceContributionRow, rows)

    def fetch_groups(
        self, publication_ids: Sequence[int]
    ) -> tuple[dict[int, dict[int, set[int]]], dict[int, MembershipRow]]:
        """Groupes en base de ces publications : publication → groupe → contributions sources, et appartenance de chaque contribution source groupée."""
        groups: dict[int, dict[int, set[int]]] = {}
        memberships: dict[int, MembershipRow] = {}
        for row in self._conn.execute(_GROUPS_SQL, {"publications": list(publication_ids)}):
            members = groups.setdefault(row.publication_id, {}).setdefault(row.id, set())
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
        return groups, memberships

    def group_ids(self, n: int) -> list[int]:
        """`n` identifiants tirés de la séquence des groupes."""
        if not n:
            return []
        return list(self._conn.execute(_GROUP_IDS_SQL, {"n": n}).scalars())

    def write(self, plan: BatchPlan) -> None:
        """Écrit les groupes et les doublons d'auteur des publications du lot.

        Un groupe déjà en base garde son identifiant. Il garde sa personne et son mode de résolution tant que ses membres restent les mêmes. Les autres contributions sources des publications du lot perdent leur `duplicate_of`.
        """
        publication_ids, groups, removed = plan.publication_ids, plan.groups, plan.removed
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
            self._conn.execute(_DELETE_GROUPS_SQL, {"ids": list(unmatched_ids)})
        if plan.recomposed:
            self._conn.execute(_DETACH_GROUPS_SQL, {"ids": list(plan.recomposed)})
        kept = [g for g in groups if g.existing]
        if kept:
            self._conn.execute(
                _UPDATE_POSITIONS_SQL,
                {"ids": [g.id for g in kept], "positions": [g.reference_position for g in kept]},
            )
        created = [g for g in groups if not g.existing]
        if created:
            self._conn.execute(
                _INSERT_GROUPS_SQL,
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
                    "groups": [m.group for m in memberships],
                    "source_records": [m.source_record for m in memberships],
                    "methods": [m.method for m in memberships],
                    "scores": [m.score for m in memberships],
                    "margins": [m.margin for m in memberships],
                },
            )
