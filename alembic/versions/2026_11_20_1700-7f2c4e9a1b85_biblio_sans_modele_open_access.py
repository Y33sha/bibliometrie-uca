"""Clé oa_model retirée de biblio.journal

Le modèle open access des revues vient d'OpenAlex au niveau de la revue (`model_serials`). La clé `oa_model` de `biblio.journal` des enregistrements sources OpenAlex est sans lecteur.

Revision ID: 7f2c4e9a1b85
Revises: e3b7c91d4a62
Create Date: 2026-11-20 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7f2c4e9a1b85"
down_revision: str | Sequence[str] | None = "e3b7c91d4a62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE sources.source_records SET biblio = biblio #- '{journal,oa_model}'
        WHERE source = 'openalex' AND biblio->'journal' ? 'oa_model'
    """)


def downgrade() -> None:
    # La clé est sans lecteur : la normalisation OpenAlex la recrée seulement avec le code qui l'écrit.
    pass
