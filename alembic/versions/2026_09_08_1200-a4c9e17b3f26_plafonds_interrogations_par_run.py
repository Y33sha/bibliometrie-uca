"""Ajoute les clés de config des plafonds d'interrogation par run

`unpaywall_max_per_run` borne les DOI vérifiés auprès d'Unpaywall à chaque run.
`fetch_missing_max_per_source` borne les DOI interrogés par source cible au
cross-import. Zéro vaut illimité. Éditables depuis admin/config.

Revision ID: a4c9e17b3f26
Revises: f3b8d24e7a19
Create Date: 2026-09-08 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4c9e17b3f26"
down_revision: str | Sequence[str] | None = "f3b8d24e7a19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO config (key, value, description) VALUES "
        "('unpaywall_max_per_run', '10000', "
        "'Nombre maximum de DOI vérifiés auprès d''Unpaywall par run. 0 = illimité.'), "
        "('fetch_missing_max_per_source', '10000', "
        "'Nombre maximum de DOI interrogés par source cible au cross-import, par run. "
        "0 = illimité.') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM config WHERE key IN ('unpaywall_max_per_run', 'fetch_missing_max_per_source')"
    )
