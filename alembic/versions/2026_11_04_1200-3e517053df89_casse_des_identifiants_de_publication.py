"""Casse des identifiants de publication contrainte

Les colonnes de DOI sont en minuscules. Les colonnes `id_value` d'identifiants typés par `id_type` ont la casse de leur forme normalisée : majuscules pour un NNT, minuscules pour les autres.

L'unicité du DOI d'une publication porte sur `doi`. L'index des paiements APC sur `lower(doi)` disparaît : la contrainte unique `apc_payments_payment_key` commence par `doi`.

Revision ID: 3e517053df89
Revises: d5b9a3c7e1f4
Create Date: 2026-11-04 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3e517053df89"
down_revision: str | Sequence[str] | None = "d5b9a3c7e1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOI_COLUMNS = (
    ("publications", "publications", "doi"),
    ("publications", "publication_relations", "target_doi"),
    ("publishing", "apc_payments", "doi"),
    ("sources", "doi_targets", "doi"),
    ("sources", "doi_targets", "target_doi"),
    ("sources", "dois", "doi"),
    ("sources", "staging", "doi"),
)
"""Colonnes de DOI : schéma, table, colonne."""

_IDENTIFIER_TABLES = (
    ("sources", "source_record_identifiers"),
    ("sources", "failed_lookups"),
)
"""Tables d'identifiants typés par `id_type` : schéma, table."""


def upgrade() -> None:
    for schema, table, column in _DOI_COLUMNS:
        op.execute(
            f"ALTER TABLE {schema}.{table} ADD CONSTRAINT {table}_{column}_lowercase "
            f"CHECK ({column} = lower({column}))"
        )
    for schema, table in _IDENTIFIER_TABLES:
        op.execute(
            f"ALTER TABLE {schema}.{table} ADD CONSTRAINT {table}_id_value_case "
            "CHECK (id_value = CASE id_type WHEN 'nnt' THEN upper(id_value) ELSE lower(id_value) END)"
        )
    op.execute(
        "ALTER TABLE publications.publications ADD CONSTRAINT publications_doi_key UNIQUE (doi)"
    )
    op.execute("DROP INDEX publications.publications_doi_lower_key")
    op.execute("DROP INDEX publishing.idx_apc_doi")


def downgrade() -> None:
    op.execute("""
        CREATE INDEX idx_apc_doi ON publishing.apc_payments (lower(doi)) WHERE doi IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX publications_doi_lower_key
            ON publications.publications (lower(doi)) WHERE doi IS NOT NULL
    """)
    op.execute("ALTER TABLE publications.publications DROP CONSTRAINT publications_doi_key")
    for schema, table in _IDENTIFIER_TABLES:
        op.execute(f"ALTER TABLE {schema}.{table} DROP CONSTRAINT {table}_id_value_case")
    for schema, table, column in _DOI_COLUMNS:
        op.execute(f"ALTER TABLE {schema}.{table} DROP CONSTRAINT {table}_{column}_lowercase")
