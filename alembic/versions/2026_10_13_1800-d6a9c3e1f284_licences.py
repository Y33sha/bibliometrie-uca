"""Licences : type `license_type`, licence d'une notice source, licences d'une publication

`source_publications.license` : licence normalisée de la notice. `publications.license` : licence de la version éditeur. `publications.deposit_license` : licence du fichier déposé dans HAL.

Revision ID: d6a9c3e1f284
Revises: c4f8a2e6b917
Create Date: 2026-10-13 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d6a9c3e1f284"
down_revision: str | Sequence[str] | None = "c4f8a2e6b917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LICENSES = (
    "cc-by",
    "cc-by-sa",
    "cc-by-nd",
    "cc-by-nc",
    "cc-by-nc-sa",
    "cc-by-nc-nd",
    "public-domain",
    "licence-ouverte",
    "open-source",
    "repository-distribution",
    "publisher-open",
    "other-oa",
    "all-rights-reserved",
    "other",
)


def upgrade() -> None:
    values = ", ".join(f"'{v}'" for v in _LICENSES)
    op.execute(f"CREATE TYPE public.license_type AS ENUM ({values})")
    op.execute("ALTER TABLE sources.source_publications ADD COLUMN license public.license_type")
    op.execute("ALTER TABLE publications.publications ADD COLUMN license public.license_type")
    op.execute(
        "ALTER TABLE publications.publications ADD COLUMN deposit_license public.license_type"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE publications.publications DROP COLUMN deposit_license")
    op.execute("ALTER TABLE publications.publications DROP COLUMN license")
    op.execute("ALTER TABLE sources.source_publications DROP COLUMN license")
    op.execute("DROP TYPE public.license_type")
