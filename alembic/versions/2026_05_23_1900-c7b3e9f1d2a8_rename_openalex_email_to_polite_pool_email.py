"""config : renomme la clé `openalex_email` en `polite_pool_email`

La clé porte historiquement le nom d'OpenAlex, mais l'email est en réalité utilisé comme polite pool pour HAL, OpenAlex, Crossref, DataCite, Unpaywall et autres APIs documentées. Le nouveau nom reflète l'usage réel.

Aucun changement de schéma — juste un renommage de la valeur de `key` dans la table `config`. La clé `crossref_email` (override spécifique pour Crossref) reste inchangée.

Revision ID: c7b3e9f1d2a8
Revises: a4f7c1e8d2b6
Create Date: 2026-05-23 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7b3e9f1d2a8"
down_revision: str | Sequence[str] | None = "a4f7c1e8d2b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE config SET key = 'polite_pool_email' WHERE key = 'openalex_email'")


def downgrade() -> None:
    op.execute("UPDATE config SET key = 'openalex_email' WHERE key = 'polite_pool_email'")
