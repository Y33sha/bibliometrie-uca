"""Requêtes de la phase `author_grouping`."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.source_publications.metadata_correction.shared_doi import DoiClusterCase

# Notice dont le DOI a convergé sur celui d'une autre œuvre (pièce, version, copie d'un dépôt DataCite).
_CONVERGED = [
    DoiClusterCase.DATACITE_PACKAGE_PIECE,
    DoiClusterCase.DATACITE_VERSION_TO_CONCEPT,
    DoiClusterCase.DATACITE_VARIANT_TO_PRIMARY,
]

# Signatures à grouper, hors collectifs, hors notices convergées ou recopiées d'un dépôt HAL présent.
_SIGNATURES_SQL = text("""
    WITH notices AS (
        SELECT sp.id, sp.publication_id, sp.source::text AS source, sp.source_id,
               (sp.raw_metadata -> 'doi' ->> 'corrected_by') = ANY(:converged) IS TRUE AS converged
        FROM source_publications sp
        WHERE sp.publication_id = ANY(:publications)
    ), kept AS (
        SELECT n.* FROM notices n
        WHERE NOT (n.converged AND EXISTS (
                SELECT 1 FROM notices o WHERE o.publication_id = n.publication_id AND NOT o.converged))
          AND NOT (n.source = 'scanr' AND n.source_id LIKE 'hal%' AND EXISTS (
                SELECT 1 FROM notices h WHERE h.publication_id = n.publication_id AND h.source = 'hal'))
    )
    SELECT k.publication_id, k.id AS notice, sa.id, sa.author_position AS position, sa.roles,
           aik.last_name_normalized AS last_name,
           coalesce(aik.first_name_normalized, '') AS first_name,
           coalesce(aik.person_identifiers ->> 'orcid', '') AS orcid,
           coalesce(aik.person_identifiers ->> 'idref', '') AS idref
    FROM kept k
    JOIN source_authorships sa ON sa.source_publication_id = k.id
    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
    WHERE NOT sa.collective
""")

_GROUPS_SQL = text("""
    SELECT g.id, g.publication_id, gs.source_authorship_id
    FROM source_authorship_groups g
    LEFT JOIN grouped_source_authorships gs ON gs.group_id = g.id
    WHERE g.publication_id = ANY(:publications)
""")

_DELETE_MEMBERSHIPS_SQL = text("""
    DELETE FROM grouped_source_authorships gs
    USING source_authorship_groups g
    WHERE gs.group_id = g.id AND g.publication_id = ANY(:publications)
""")

_DELETE_GROUPS_SQL = text("DELETE FROM source_authorship_groups WHERE id = ANY(:ids)")

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
    id: int
    position: int | None
    roles: list[str] | None
    last_name: str
    first_name: str
    orcid: str
    idref: str


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

    def fetch_dirty_publication_ids(self, conn: Connection) -> list[int]:
        """Publications marquées `authorships_dirty`."""
        rows = conn.execute(
            text("SELECT id FROM publications WHERE authorships_dirty ORDER BY id")
        ).scalars()
        return list(rows)

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
    ) -> dict[int, dict[int, set[int]]]:
        """Signatures des groupes en base : publication → groupe → signatures."""
        out: dict[int, dict[int, set[int]]] = {}
        for row in conn.execute(_GROUPS_SQL, {"publications": list(publication_ids)}):
            members = out.setdefault(row.publication_id, {}).setdefault(row.id, set())
            if row.source_authorship_id is not None:
                members.add(row.source_authorship_id)
        return out

    def group_ids(self, conn: Connection, n: int) -> list[int]:
        """`n` identifiants tirés de la séquence des groupes."""
        if not n:
            return []
        return list(conn.execute(_GROUP_IDS_SQL, {"n": n}).scalars())

    def write(
        self,
        conn: Connection,
        publication_ids: Sequence[int],
        groups: Sequence[GroupRow],
        memberships: Sequence[MembershipRow],
        unmatched_ids: Sequence[int],
    ) -> None:
        """Écrit les groupes de ces publications et retire leur drapeau `authorships_dirty`.

        Un groupe déjà en base garde son identifiant, sa personne et son mode de résolution. Les groupes `unmatched_ids` sont supprimés.
        """
        conn.execute(_DELETE_MEMBERSHIPS_SQL, {"publications": list(publication_ids)})
        # Signature d'une notice venue d'une autre publication, encore rattachée à un groupe de celle-ci.
        conn.execute(
            text("DELETE FROM grouped_source_authorships WHERE source_authorship_id = ANY(:ids)"),
            {"ids": [m.signature for m in memberships]},
        )
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
