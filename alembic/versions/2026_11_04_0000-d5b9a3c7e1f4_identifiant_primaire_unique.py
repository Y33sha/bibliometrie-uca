"""Au plus un identifiant primaire par enregistrement source

Statistiques de `source_record_identifiers` recalculées après le changement de type de `id_type`.

Revision ID: d5b9a3c7e1f4
Revises: c3a7e5f1d9b2
Create Date: 2026-11-04 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d5b9a3c7e1f4"
down_revision: str | Sequence[str] | None = "c3a7e5f1d9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_COMMENT = (
    "primary : identifiant de l''enregistrement dans la source.{primary} "
    "derived : identifiant de l''enregistrement d''une autre source dont l''enregistrement source "
    "est dérivé. Un enregistrement source a au plus un identifiant dérivé. "
    "secondary : identifiant que la source attribue au même document. "
    "related : identifiant d''un document lié."
)


def _comment_role(primary: str) -> None:
    op.execute(
        "COMMENT ON COLUMN sources.source_record_identifiers.role IS '"
        + _ROLE_COMMENT.format(primary=primary)
        + "'"
    )


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX uq_source_record_identifiers_primary
            ON sources.source_record_identifiers (source_record_id) WHERE role = 'primary'
    """)
    _comment_role(" Un enregistrement source a au plus un identifiant primaire.")
    # La migration précédente change le type de `id_type` : les statistiques de la colonne sont à recalculer.
    op.execute("ANALYZE sources.source_record_identifiers")


def downgrade() -> None:
    op.execute("DROP INDEX sources.uq_source_record_identifiers_primary")
    _comment_role("")
