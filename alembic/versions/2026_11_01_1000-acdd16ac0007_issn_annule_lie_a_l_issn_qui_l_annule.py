"""ISSN annulé lié à l'ISSN de la notice Sudoc qui l'annule

Revision ID: acdd16ac0007
Revises: 2ac26ec26f63
Create Date: 2026-11-01 10:00:00.000000

`issn_link_type` reçoit `replaced_by` : ISSN annulé vers l'ISSN de la notice Sudoc qui l'annule. La table ISSN-L de l'ISSN International Centre omet les ISSN annulés ; le rattachement leur donne l'ISSN-L de l'ISSN qui les annule. Les ISSN annulés sont vérifiés de nouveau dans le Sudoc, pour écrire ce lien.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "acdd16ac0007"
down_revision: str | Sequence[str] | None = "2ac26ec26f63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMENT = (
    "COMMENT ON TABLE publishing.issn_links IS "
    "'Liens entre ISSN lus dans le Sudoc, une ligne par lien : continued_by, titre précédent "
    "vers titre suivant ; supplement, revue principale vers supplément{}.'"
)


def upgrade() -> None:
    op.execute("ALTER TYPE public.issn_link_type ADD VALUE IF NOT EXISTS 'replaced_by'")
    op.execute(
        _COMMENT.format(" ; replaced_by, ISSN annulé vers l''ISSN de la notice Sudoc qui l''annule")
    )
    op.execute(
        "UPDATE publishing.serial_issns SET sudoc_checked_at = NULL WHERE status = 'cancelled'"
    )


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum : le type est recréé sans `replaced_by`.
    op.execute("DELETE FROM publishing.issn_links WHERE link_type = 'replaced_by'")
    op.execute("ALTER TYPE public.issn_link_type RENAME TO issn_link_type_old")
    op.execute("CREATE TYPE public.issn_link_type AS ENUM ('continued_by', 'supplement')")
    op.execute(
        "ALTER TABLE publishing.issn_links ALTER COLUMN link_type TYPE public.issn_link_type"
        " USING link_type::text::public.issn_link_type"
    )
    op.execute("DROP TYPE public.issn_link_type_old")
    op.execute(_COMMENT.format(""))
