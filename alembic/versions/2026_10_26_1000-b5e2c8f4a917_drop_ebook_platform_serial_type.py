"""Type ebook_platform retiré des publications en série

Revision ID: b5e2c8f4a917
Revises: a7d3e9f1c5b8
Create Date: 2026-10-26 10:00:00.000000

Une plateforme d'ebooks n'est pas une publication en série. Les entrées de ce type passent en `unknown`, sans marque de saisie manuelle du type, et l'énumération `serial_type` perd la valeur `ebook_platform`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b5e2c8f4a917"
down_revision: str | Sequence[str] | None = "a7d3e9f1c5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _recreate_type(values: str, old_name: str) -> str:
    return f"""
        ALTER TYPE public.serial_type RENAME TO {old_name};
        CREATE TYPE public.serial_type AS ENUM ({values});
        ALTER TABLE publishing.serials ALTER COLUMN serial_type DROP DEFAULT;
        ALTER TABLE publishing.serials
            ALTER COLUMN serial_type TYPE public.serial_type
            USING serial_type::text::public.serial_type;
        ALTER TABLE publishing.serials ALTER COLUMN serial_type SET DEFAULT 'unknown';
        DROP TYPE public.{old_name};
    """


def upgrade() -> None:
    op.execute(
        """
        UPDATE publishing.serials
        SET serial_type = 'unknown', manual_fields = array_remove(manual_fields, 'serial_type')
        WHERE serial_type = 'ebook_platform';
        """
        + _recreate_type(
            "'journal', 'proceedings', 'repository', 'book_series', 'preprint_server', 'media', 'unknown'",
            "serial_type_with_ebook_platform",
        )
    )


def downgrade() -> None:
    op.execute(
        _recreate_type(
            "'journal', 'proceedings', 'repository', 'book_series', 'preprint_server', 'media', "
            "'ebook_platform', 'unknown'",
            "serial_type_without_ebook_platform",
        )
    )
