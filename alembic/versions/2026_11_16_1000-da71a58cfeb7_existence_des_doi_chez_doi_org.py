"""Existence des DOI chez doi.org dans dois

La colonne `dois.registered` donne la réponse de doi.org : TRUE pour un DOI connu, FALSE pour un DOI inconnu, NULL sans réponse. Une URL nulle avec une date confondait un DOI inconnu et un DOI connu sans URL : ces lignes perdent leur date, et le DOI est interrogé de nouveau. Les DOI inconnus de doi.org inscrits dans `failed_lookups` passent dans `dois`.

Revision ID: da71a58cfeb7
Revises: 4f2a9c7d1e35
Create Date: 2026-11-16 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "da71a58cfeb7"
down_revision: str | Sequence[str] | None = "4f2a9c7d1e35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_COMMENT = (
    "Réponses des services externes sur chaque DOI connu : existence et URL de résolution "
    "chez doi.org, verdict d'Unpaywall."
)
_PREVIOUS_TABLE_COMMENT = (
    "Réponses des services externes sur chaque DOI de publication : verdict d'Unpaywall, "
    "URL de résolution chez doi.org."
)
_REGISTERED_URL_COMMENT = (
    "URL de résolution du DOI, lue dans l'API des handles de doi.org. NULL pour un DOI "
    "inconnu, ou connu sans URL."
)
_PREVIOUS_REGISTERED_URL_COMMENT = (
    "URL de résolution du DOI, lue dans l'API des handles de doi.org. NULL avec une date : "
    "DOI inconnu de doi.org."
)


def upgrade() -> None:
    op.add_column(
        "dois",
        sa.Column(
            "registered",
            sa.Boolean,
            comment="Réponse de doi.org : TRUE pour un DOI connu, FALSE pour un DOI inconnu. NULL sans réponse.",
        ),
        schema="sources",
    )
    op.execute("UPDATE sources.dois SET registered = TRUE WHERE registered_url IS NOT NULL")
    op.execute("UPDATE sources.dois SET resolved_at = NULL WHERE registered_url IS NULL")
    op.execute("""
        INSERT INTO sources.dois (doi, registered, resolved_at)
        SELECT id_value, FALSE, not_found_at FROM sources.failed_lookups
        WHERE source = 'doi_org' AND id_type = 'doi'
        ON CONFLICT (doi) DO UPDATE
        SET registered = FALSE, resolved_at = EXCLUDED.resolved_at
        WHERE sources.dois.registered IS NULL
    """)
    op.execute("DELETE FROM sources.failed_lookups WHERE source = 'doi_org'")
    op.drop_constraint("dois_registered_url_dated", "dois", schema="sources")
    op.create_check_constraint(
        "dois_registered_dated",
        "dois",
        "(registered IS NULL) = (resolved_at IS NULL)",
        schema="sources",
    )
    op.create_check_constraint(
        "dois_registered_url_registered",
        "dois",
        "registered_url IS NULL OR registered",
        schema="sources",
    )
    op.alter_column("dois", "registered_url", comment=_REGISTERED_URL_COMMENT, schema="sources")
    op.alter_column(
        "dois", "resolved_at", comment="Date de la réponse de doi.org.", schema="sources"
    )
    op.create_table_comment("dois", _TABLE_COMMENT, schema="sources")


def downgrade() -> None:
    op.execute("""
        INSERT INTO sources.failed_lookups (source, id_type, id_value, not_found_at)
        SELECT 'doi_org', 'doi', doi, resolved_at FROM sources.dois WHERE registered = FALSE
    """)
    op.execute("UPDATE sources.dois SET resolved_at = NULL WHERE registered = FALSE")
    op.drop_constraint("dois_registered_url_registered", "dois", schema="sources")
    op.drop_constraint("dois_registered_dated", "dois", schema="sources")
    op.create_check_constraint(
        "dois_registered_url_dated",
        "dois",
        "registered_url IS NULL OR resolved_at IS NOT NULL",
        schema="sources",
    )
    op.drop_column("dois", "registered", schema="sources")
    op.alter_column(
        "dois", "registered_url", comment=_PREVIOUS_REGISTERED_URL_COMMENT, schema="sources"
    )
    op.alter_column(
        "dois", "resolved_at", comment="Date de la lecture chez doi.org.", schema="sources"
    )
    op.create_table_comment("dois", _PREVIOUS_TABLE_COMMENT, schema="sources")
