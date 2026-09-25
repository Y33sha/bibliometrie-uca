"""Ajoute la valeur 'conference' à l'enum doc_type

Une communication sans texte publié, résumés compris, se distingue du texte publié dans des actes (`conference_paper`).

Revision ID: f1c8b3d6a472
Revises: c4a9e1f7d253
Create Date: 2026-09-25 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1c8b3d6a472"
down_revision: str | Sequence[str] | None = "c4a9e1f7d253"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALUES_WITHOUT_CONFERENCE = (
    "'article', 'conference_paper', 'book', 'book_chapter', 'thesis', 'ongoing_thesis', "
    "'preprint', 'review', 'editorial', 'report', 'peer_review', 'other', 'dataset', "
    "'software', 'patent', 'hdr', 'memoir', 'poster', 'letter', 'erratum', 'retraction', "
    "'book_review', 'data_paper', 'proceedings', 'media'"
)


def upgrade() -> None:
    op.execute("ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'conference' AFTER 'conference_paper'")


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade recrée le type sans
    # 'conference' : les publications qui le portent reviennent à 'conference_paper'.
    op.execute(
        "UPDATE publications SET doc_type = 'conference_paper' WHERE doc_type = 'conference'"
    )
    op.execute(
        "UPDATE source_publications SET doc_type = 'conference_paper' WHERE doc_type = 'conference'"
    )
    op.execute("ALTER TYPE doc_type RENAME TO doc_type_old")
    op.execute(f"CREATE TYPE doc_type AS ENUM ({_VALUES_WITHOUT_CONFERENCE})")
    op.execute(
        "ALTER TABLE publications ALTER COLUMN doc_type DROP DEFAULT, "
        "ALTER COLUMN doc_type TYPE doc_type USING doc_type::text::doc_type, "
        "ALTER COLUMN doc_type SET DEFAULT 'other'"
    )
    op.execute("DROP TYPE doc_type_old")
