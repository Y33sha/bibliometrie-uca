"""Requêtes de la phase `author_grouping`."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.persons.identifiers import AttributionStatus
from domain.source_publications.metadata_correction.shared_doi import DoiClusterCase
from infrastructure.sql_fragments import corrected_by, in_clause, usable_identifier

# Notice dont le DOI a convergé sur celui d'une autre œuvre (pièce, version, copie d'un dépôt DataCite).
_CONVERGED = [
    DoiClusterCase.DATACITE_PACKAGE_PIECE,
    DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
    DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
]

# Statuts d'un rattachement d'identifiant posé par un humain.
_HUMAN_STATUSES = (AttributionStatus.CONFIRMED.value, AttributionStatus.AUTHENTICATED.value)


def _known_first_name(id_type: str) -> str:
    """Prénom normalisé de la personne à laquelle un humain a rattaché l'identifiant `id_type` de la signature `sa`, s'il n'est pas neutralisé."""
    return f"""(
        SELECT p.first_name_normalized FROM person_identifiers pi JOIN persons p ON p.id = pi.person_id
        WHERE pi.id_type = '{id_type}' AND pi.id_value = {usable_identifier(f"'{id_type}'")}
          AND pi.status::text IN {in_clause(_HUMAN_STATUSES)}
    )"""


# Signatures à grouper, hors collectifs, hors notices convergées ou recopiées d'un dépôt HAL présent.
_SIGNATURES_SQL = text(f"""
    WITH notices AS (
        SELECT sp.id, sp.publication_id, sp.source::text AS source, sp.source_id,
               ({corrected_by("doi")}) = ANY(:converged) IS TRUE AS converged
        FROM source_publications sp
        WHERE sp.publication_id = ANY(:publications)
    ), kept AS (
        SELECT n.* FROM notices n
        WHERE NOT (n.converged AND EXISTS (
                SELECT 1 FROM notices o WHERE o.publication_id = n.publication_id AND NOT o.converged))
          AND NOT (n.source = 'scanr' AND n.source_id LIKE 'hal%' AND EXISTS (
                SELECT 1 FROM notices h WHERE h.publication_id = n.publication_id AND h.source = 'hal'))
    )
    SELECT k.publication_id, k.id AS notice, k.source, sa.id, sa.author_position AS position,
           aik.last_name_normalized AS last_name,
           coalesce(aik.first_name_normalized, '') AS first_name,
           coalesce({usable_identifier("'orcid'")}, '') AS orcid,
           coalesce({usable_identifier("'idref'")}, '') AS idref,
           coalesce({_known_first_name("orcid")}, {_known_first_name("idref")}, '') AS known_first_name
    FROM kept k
    JOIN source_authorships sa ON sa.source_publication_id = k.id
    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
    WHERE NOT sa.collective
""")

_GROUPS_SQL = text("""
    SELECT g.id, g.publication_id, gs.source_authorship_id, gs.source_publication_id,
           gs.method::text AS method, gs.score, gs.margin
    FROM source_authorship_groups g
    LEFT JOIN grouped_source_authorships gs ON gs.group_id = g.id
    WHERE g.publication_id = ANY(:publications)
""")

_DELETE_MEMBERSHIPS_SQL = text(
    "DELETE FROM grouped_source_authorships WHERE source_authorship_id = ANY(:signatures)"
)

_DELETE_GROUPS_SQL = text("DELETE FROM source_authorship_groups WHERE id = ANY(:ids)")

_CLEAR_COPIES_SQL = text("""
    UPDATE source_authorships sa SET duplicate_of = NULL
    FROM source_publications sp
    WHERE sa.source_publication_id = sp.id AND sp.publication_id = ANY(:publications)
      AND sa.duplicate_of IS NOT NULL AND sa.id <> ALL(CAST(:copies AS integer[]))
""")

_SET_COPIES_SQL = text("""
    UPDATE source_authorships sa SET duplicate_of = u.original
    FROM unnest(CAST(:copies AS integer[]), CAST(:originals AS integer[])) AS u(id, original)
    WHERE sa.id = u.id AND sa.duplicate_of IS DISTINCT FROM u.original
""")

_UPDATE_POSITIONS_SQL = text("""
    UPDATE source_authorship_groups g SET reference_position = u.position
    FROM unnest(CAST(:ids AS integer[]), CAST(:positions AS smallint[])) AS u(id, position)
    WHERE g.id = u.id
""")

_GROUP_IDS_SQL = text(
    "SELECT nextval(pg_get_serial_sequence('publications.source_authorship_groups', 'id'))"
    " FROM generate_series(1, :n)"
)

_INSERT_GROUPS_SQL = text("""
    INSERT INTO source_authorship_groups (id, publication_id, reference_position)
    SELECT * FROM unnest(
        CAST(:ids AS integer[]), CAST(:publications AS integer[]), CAST(:positions AS smallint[]))
""")

_INSERT_MEMBERSHIPS_SQL = text("""
    INSERT INTO grouped_source_authorships
        (source_authorship_id, group_id, source_publication_id, method, score, margin)
    SELECT * FROM unnest(
        CAST(:signatures AS integer[]), CAST(:groups AS integer[]), CAST(:notices AS integer[]),
        CAST(:methods AS grouping_method[]), CAST(:scores AS real[]), CAST(:margins AS real[]))
""")


@dataclass(frozen=True, slots=True)
class SignatureRow:
    """Signature à grouper, telle que la base la rend."""

    publication_id: int
    notice: int
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
    """Appartenance d'une signature à un groupe."""

    signature: int
    group: int
    notice: int
    method: str
    score: float | None
    margin: float | None


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """Écritures d'un lot de publications."""

    publication_ids: Sequence[int]
    groups: list[GroupRow]
    removed: list[int]
    """Signatures dont l'appartenance en base est supprimée."""
    memberships: list[MembershipRow]
    """Appartenances à insérer."""
    unmatched: list[int]
    """Groupes en base sans correspondant, supprimés."""
    copies: dict[int, int]
    """Doublon d'auteur → première occurrence de son nom (`duplicate_of`)."""


class AuthorGroupingQueries:
    """Lectures et écritures des groupes de signatures."""

    def delete_orphan_groups(self, conn: Connection) -> int:
        """Supprime les groupes des publications supprimées, et leurs appartenances. Rend le nombre de groupes supprimés."""
        count = conn.execute(
            text("""
                WITH orphans AS (
                    DELETE FROM source_authorship_groups g
                    WHERE NOT EXISTS (SELECT 1 FROM publications p WHERE p.id = g.publication_id)
                    RETURNING g.id
                ), memberships AS (
                    DELETE FROM grouped_source_authorships gs
                    USING orphans o WHERE gs.group_id = o.id
                )
                SELECT count(*) FROM orphans
            """)
        ).scalar_one()
        return int(count)

    def refresh_alignment(self, conn: Connection) -> None:
        """Rafraîchit `publication_author_alignment`, le recouvrement des listes d'auteurs de chaque publication."""
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_author_alignment"))

    def fetch_dirty_publications(self, conn: Connection) -> list[tuple[int, int]]:
        """Publications marquées `authorships_dirty`, avec le nombre de signatures d'auteur de leurs notices (`author_count`)."""
        rows = conn.execute(
            text("""
                SELECT p.id, coalesce(sum(sp.author_count), 0)::integer AS signatures
                FROM publications p
                LEFT JOIN source_publications sp ON sp.publication_id = p.id
                WHERE p.authorships_dirty
                GROUP BY p.id
                ORDER BY p.id
            """)
        ).all()
        return [(r.id, r.signatures) for r in rows]

    def fetch_signatures(
        self, conn: Connection, publication_ids: Sequence[int]
    ) -> list[SignatureRow]:
        """Signatures à grouper de ces publications."""
        rows = conn.execute(
            _SIGNATURES_SQL,
            {"publications": list(publication_ids), "converged": [str(c) for c in _CONVERGED]},
        ).mappings()
        return [SignatureRow(**row) for row in rows]

    def fetch_groups(
        self, conn: Connection, publication_ids: Sequence[int]
    ) -> tuple[dict[int, dict[int, set[int]]], dict[int, MembershipRow]]:
        """Groupes en base de ces publications : publication → groupe → signatures, et appartenance de chaque signature groupée."""
        groups: dict[int, dict[int, set[int]]] = {}
        memberships: dict[int, MembershipRow] = {}
        for row in conn.execute(_GROUPS_SQL, {"publications": list(publication_ids)}):
            members = groups.setdefault(row.publication_id, {}).setdefault(row.id, set())
            if row.source_authorship_id is not None:
                members.add(row.source_authorship_id)
                memberships[row.source_authorship_id] = MembershipRow(
                    row.source_authorship_id,
                    row.id,
                    row.source_publication_id,
                    row.method,
                    row.score,
                    row.margin,
                )
        return groups, memberships

    def group_ids(self, conn: Connection, n: int) -> list[int]:
        """`n` identifiants tirés de la séquence des groupes."""
        if not n:
            return []
        return list(conn.execute(_GROUP_IDS_SQL, {"n": n}).scalars())

    def write(self, conn: Connection, plan: BatchPlan) -> None:
        """Écrit les groupes et les doublons d'auteur des publications du lot, et retire leur drapeau `authorships_dirty`.

        Un groupe déjà en base garde son identifiant, sa personne et son mode de résolution. Les autres signatures des publications du lot perdent leur `duplicate_of`.
        """
        publication_ids, groups, removed = plan.publication_ids, plan.groups, plan.removed
        memberships, unmatched_ids, copies = plan.memberships, plan.unmatched, plan.copies
        conn.execute(
            _CLEAR_COPIES_SQL, {"publications": list(publication_ids), "copies": list(copies)}
        )
        if copies:
            conn.execute(
                _SET_COPIES_SQL, {"copies": list(copies), "originals": list(copies.values())}
            )
        if removed:
            conn.execute(_DELETE_MEMBERSHIPS_SQL, {"signatures": list(removed)})
        if unmatched_ids:
            conn.execute(_DELETE_GROUPS_SQL, {"ids": list(unmatched_ids)})
        kept = [g for g in groups if g.existing]
        if kept:
            conn.execute(
                _UPDATE_POSITIONS_SQL,
                {"ids": [g.id for g in kept], "positions": [g.reference_position for g in kept]},
            )
        created = [g for g in groups if not g.existing]
        if created:
            conn.execute(
                _INSERT_GROUPS_SQL,
                {
                    "ids": [g.id for g in created],
                    "publications": [g.publication_id for g in created],
                    "positions": [g.reference_position for g in created],
                },
            )
        if memberships:
            conn.execute(
                _INSERT_MEMBERSHIPS_SQL,
                {
                    "signatures": [m.signature for m in memberships],
                    "groups": [m.group for m in memberships],
                    "notices": [m.notice for m in memberships],
                    "methods": [m.method for m in memberships],
                    "scores": [m.score for m in memberships],
                    "margins": [m.margin for m in memberships],
                },
            )
        conn.execute(
            text("UPDATE publications SET authorships_dirty = false WHERE id = ANY(:ids)"),
            {"ids": list(publication_ids)},
        )
