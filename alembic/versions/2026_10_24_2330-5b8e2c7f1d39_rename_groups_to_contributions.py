"""Groupes renommés : contributions et aligned_source_contributions

Revision ID: 5b8e2c7f1d39
Revises: 2d9f6b3e8a14
Create Date: 2026-10-24 23:30:00.000000

Le groupe de contributions sources est la contribution : `source_contribution_groups` devient `contributions`, `source_contribution_group_members` devient `aligned_source_contributions`, sa colonne `group_id` devient `contribution_id`. Suivent la vue matérialisée `contribution_structures`, les files `contribution_resolution_queue` et `contribution_attributes_queue`, l'énumération `resolution_mode`, et les séquences, contraintes et index qui portent ces noms.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5b8e2c7f1d39"
down_revision: str | Sequence[str] | None = "2d9f6b3e8a14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_P, _Q = "publications", "queues"

# Tables, vue et énumération : (genre, schéma, ancien nom, nouveau nom).
_RELATIONS = [
    ("TABLE", _P, "source_contribution_groups", "contributions"),
    ("TABLE", _P, "source_contribution_group_members", "aligned_source_contributions"),
    ("MATERIALIZED VIEW", _P, "group_structures", "contribution_structures"),
    ("TABLE", _Q, "group_resolution_queue", "contribution_resolution_queue"),
    ("TABLE", _Q, "source_contribution_group_attributes_queue", "contribution_attributes_queue"),
    ("TYPE", "public", "group_resolution_mode", "resolution_mode"),
]

# Colonnes : (genre, relation nouvellement nommée, ancien nom, nouveau nom).
_COLUMNS = [
    ("TABLE", f"{_P}.aligned_source_contributions", "group_id", "contribution_id"),
    ("MATERIALIZED VIEW", f"{_P}.contribution_structures", "group_id", "contribution_id"),
]

# Séquences et index : (genre, schéma, ancien nom, nouveau nom).
_OBJECTS = [
    ("SEQUENCE", _P, "source_contribution_groups_id_seq", "contributions_id_seq"),
    ("SEQUENCE", _Q, "group_resolution_queue_seq_seq", "contribution_resolution_queue_seq_seq"),
    (
        "SEQUENCE",
        _Q,
        "source_contribution_group_attributes_queue_seq_seq",
        "contribution_attributes_queue_seq_seq",
    ),
    ("INDEX", _P, "source_contribution_groups_orphans_idx", "contributions_orphans_idx"),
    ("INDEX", _P, "source_contribution_groups_person_id_idx", "contributions_person_id_idx"),
    (
        "INDEX",
        _P,
        "ix_source_contribution_group_members_source_record_id",
        "ix_aligned_source_contributions_source_record_id",
    ),
    ("INDEX", _P, "group_structures_pkey", "contribution_structures_pkey"),
    ("INDEX", _P, "idx_group_structures_structure_id", "idx_contribution_structures_structure_id"),
]

# Contraintes : (table nouvellement nommée, ancien nom, nouveau nom). Renommer une contrainte d'unicité renomme son index.
_CONSTRAINTS = [
    (f"{_P}.contributions", "source_contribution_groups_pkey", "contributions_pkey"),
    (
        f"{_P}.contributions",
        "source_contribution_groups_publication_person_uq",
        "contributions_publication_person_uq",
    ),
    (
        f"{_P}.contributions",
        "source_contribution_groups_person_id_fkey",
        "contributions_person_id_fkey",
    ),
    (
        f"{_P}.contributions",
        "source_contribution_groups_publication_id_fkey",
        "contributions_publication_id_fkey",
    ),
    (
        f"{_P}.contributions",
        "source_contribution_groups_resolution_mode_with_person",
        "contributions_resolution_mode_with_person",
    ),
    (f"{_P}.contributions", "source_contribution_groups_id_not_null", "contributions_id_not_null"),
    (
        f"{_P}.contributions",
        "source_contribution_groups_publication_id_not_null",
        "contributions_publication_id_not_null",
    ),
    (
        f"{_P}.contributions",
        "source_contribution_groups_perimeter_evidence_not_null",
        "contributions_perimeter_evidence_not_null",
    ),
    (
        f"{_P}.contributions",
        "source_contribution_groups_in_perimeter_not_null",
        "contributions_in_perimeter_not_null",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_members_pkey",
        "aligned_source_contributions_pkey",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_members_group_record_uq",
        "aligned_source_contributions_contribution_record_uq",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_members_group_id_fkey",
        "aligned_source_contributions_contribution_id_fkey",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_members_source_record_id_fkey",
        "aligned_source_contributions_source_record_id_fkey",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_members_source_contribution_id_fkey",
        "aligned_source_contributions_source_contribution_id_fkey",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_members_score_check",
        "aligned_source_contributions_score_check",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_membe_source_contribution_id_not_null",
        "aligned_source_contributions_source_contribution_id_not_null",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_members_group_id_not_null",
        "aligned_source_contributions_contribution_id_not_null",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_members_source_record_id_not_null",
        "aligned_source_contributions_source_record_id_not_null",
    ),
    (
        f"{_P}.aligned_source_contributions",
        "source_contribution_group_members_method_not_null",
        "aligned_source_contributions_method_not_null",
    ),
    (
        f"{_Q}.contribution_resolution_queue",
        "group_resolution_queue_pkey",
        "contribution_resolution_queue_pkey",
    ),
    (
        f"{_Q}.contribution_resolution_queue",
        "group_resolution_queue_id_fkey",
        "contribution_resolution_queue_id_fkey",
    ),
    (
        f"{_Q}.contribution_resolution_queue",
        "group_resolution_queue_id_not_null",
        "contribution_resolution_queue_id_not_null",
    ),
    (
        f"{_Q}.contribution_resolution_queue",
        "group_resolution_queue_seq_not_null",
        "contribution_resolution_queue_seq_not_null",
    ),
    (
        f"{_Q}.contribution_attributes_queue",
        "source_contribution_group_attributes_queue_pkey",
        "contribution_attributes_queue_pkey",
    ),
    (
        f"{_Q}.contribution_attributes_queue",
        "source_contribution_group_attributes_queue_id_not_null",
        "contribution_attributes_queue_id_not_null",
    ),
    (
        f"{_Q}.contribution_attributes_queue",
        "source_contribution_group_attributes_queue_seq_not_null",
        "contribution_attributes_queue_seq_not_null",
    ),
]


def _statements(*, up: bool) -> list[str]:
    """Renommages de la montée, ou de la descente dans l'ordre inverse. Colonnes et contraintes se renomment sur les relations déjà renommées à la montée, encore renommées à la descente."""

    def pair(old: str, new: str) -> tuple[str, str]:
        return (old, new) if up else (new, old)

    relations = [
        "ALTER {} {}.{} RENAME TO {}".format(kind, schema, *pair(old, new))
        for kind, schema, old, new in _RELATIONS
    ]
    columns = [
        "ALTER {} {} RENAME COLUMN {} TO {}".format(kind, relation, *pair(old, new))
        for kind, relation, old, new in _COLUMNS
    ]
    objects = [
        "ALTER {} {}.{} RENAME TO {}".format(kind, schema, *pair(old, new))
        for kind, schema, old, new in _OBJECTS
    ]
    constraints = [
        "ALTER TABLE {} RENAME CONSTRAINT {} TO {}".format(table, *pair(old, new))
        for table, old, new in _CONSTRAINTS
    ]
    if up:
        return relations + columns + objects + constraints
    return constraints + objects + columns + relations


def upgrade() -> None:
    op.execute(";\n".join(_statements(up=True)))


def downgrade() -> None:
    op.execute(";\n".join(_statements(up=False)))
