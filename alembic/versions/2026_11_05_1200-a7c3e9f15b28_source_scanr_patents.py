"""Source scanr_patents et numéros de brevet

La source `scanr_patents` reçoit les familles de brevets de l'index `scanr-patents` de ScanR. Les types d'identifiant `patent_publication_number` et `patent_application_number` reçoivent les numéros de publication et de demande, en majuscules comme le NNT.

Revision ID: a7c3e9f15b28
Revises: 90d4bdd8877d
Create Date: 2026-11-05 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c3e9f15b28"
down_revision: str | Sequence[str] | None = "90d4bdd8877d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPPERCASE = "('nnt', 'patent_publication_number', 'patent_application_number')"


def _replace_case_constraint(table: str, uppercase: str) -> None:
    op.execute(f"""
        ALTER TABLE sources.{table} DROP CONSTRAINT {table}_id_value_case;
        ALTER TABLE sources.{table} ADD CONSTRAINT {table}_id_value_case CHECK (
            id_value = CASE WHEN id_type::text IN {uppercase}
                THEN upper(id_value) ELSE lower(id_value) END
        );
    """)


def upgrade() -> None:
    op.execute("ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'scanr_patents' AFTER 'scanr'")
    op.execute("ALTER TYPE lookup_source ADD VALUE IF NOT EXISTS 'scanr_patents' AFTER 'scanr'")
    op.execute(
        "ALTER TYPE source_identifier_type ADD VALUE IF NOT EXISTS 'patent_publication_number'"
    )
    op.execute(
        "ALTER TYPE source_identifier_type ADD VALUE IF NOT EXISTS 'patent_application_number'"
    )
    # La comparaison en texte évite d'employer les valeurs ajoutées dans la transaction qui les crée.
    for table in ("source_record_identifiers", "failed_lookups"):
        _replace_case_constraint(table, _UPPERCASE)


def downgrade() -> None:
    # Postgres ne sait pas retirer une valeur d'enum. Le downgrade supprime les numéros de brevet
    # et laisse les valeurs dans les types, inutilisées.
    op.execute("""
        DELETE FROM sources.source_record_identifiers
        WHERE id_type::text IN ('patent_publication_number', 'patent_application_number');
    """)
    for table in ("source_record_identifiers", "failed_lookups"):
        _replace_case_constraint(table, "('nnt')")
