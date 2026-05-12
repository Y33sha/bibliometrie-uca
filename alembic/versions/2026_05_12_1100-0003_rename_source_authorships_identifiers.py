"""rename source_authorships.identifiers → person_identifiers

Préparatif Phase 2 du chantier `DATA_simplify-source-tables.md` : clarifier
la sémantique de la colonne. « identifiers » tout court ne précise pas
de quelle entité on parle ; or sur une `source_authorship`, ces
identifiants concernent uniquement la **personne** (orcid, idhal, idref,
hal_person_id). Le renommage `person_identifiers` lève l'ambiguïté sans
préjuger d'un import ultérieur dans la table canonique du même nom.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-12 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("source_authorships", "identifiers", new_column_name="person_identifiers")


def downgrade() -> None:
    op.alter_column("source_authorships", "person_identifiers", new_column_name="identifiers")
