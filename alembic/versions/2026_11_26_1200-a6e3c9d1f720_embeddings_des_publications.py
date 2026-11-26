"""Embeddings des publications

Table `publications.publication_embeddings` : vecteur de chaque publication, calculé par la phase `embeddings` sur le titre suivi du résumé, avec le modèle et l'empreinte du texte encodé. Clé `embeddings_max_per_run` : plafond de publications encodées par run, 3 000 par défaut. La contrainte des plafonds couvre la clé.

Revision ID: a6e3c9d1f720
Revises: d4b8f2a05c31
Create Date: 2026-11-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, REAL

from alembic import op

revision: str = "a6e3c9d1f720"
down_revision: str | Sequence[str] | None = "d4b8f2a05c31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAP_KEYS = (
    "('doi_resolution_max_per_run', 'fetch_missing_max_per_source', "
    "'fetch_stale_max_per_source', 'sudoc_max_per_run', 'unpaywall_max_per_run')"
)
_CAP_KEYS_WITH_EMBEDDINGS = (
    "('doi_resolution_max_per_run', 'embeddings_max_per_run', 'fetch_missing_max_per_source', "
    "'fetch_stale_max_per_source', 'sudoc_max_per_run', 'unpaywall_max_per_run')"
)


def _cap_constraint(keys: str) -> str:
    return (
        "ALTER TABLE ops.config ADD CONSTRAINT config_cap_is_non_negative_integer CHECK ("
        f"  key NOT IN {keys}"
        "  OR (jsonb_typeof(value) = 'number' AND (value)::numeric >= 0"
        "      AND (value)::numeric = trunc((value)::numeric)))"
    )


def upgrade() -> None:
    op.create_table(
        "publication_embeddings",
        sa.Column("publication_id", sa.Integer, primary_key=True),
        sa.Column("model", sa.Text, nullable=False, comment="Modèle d'embeddings du vecteur."),
        sa.Column(
            "text_hash",
            sa.Text,
            nullable=False,
            comment="Empreinte du début du texte encodé : un texte modifié au-delà reste lu à l'identique par le modèle.",
        ),
        sa.Column("vector", ARRAY(REAL), nullable=False, comment="Vecteur normalisé."),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.publications.id"],
            name="publication_embeddings_publication_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cardinality(vector) > 0", name="publication_embeddings_vector_not_empty"
        ),
        comment=(
            "Embedding de chaque publication : titre suivi du résumé, encodés par le modèle `model`. "
            "La phase `embeddings` encode les publications sans vecteur, ou dont le modèle ou l'empreinte du texte diffère."
        ),
        schema="publications",
    )
    op.execute(
        "INSERT INTO ops.config (key, value, description) VALUES "
        "('embeddings_max_per_run', '3000', "
        "'Nombre maximum de publications encodées par la phase embeddings, par run. 0 = illimité.') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_cap_is_non_negative_integer")
    op.execute(_cap_constraint(_CAP_KEYS_WITH_EMBEDDINGS))


def downgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_cap_is_non_negative_integer")
    op.execute(_cap_constraint(_CAP_KEYS))
    op.execute("DELETE FROM ops.config WHERE key = 'embeddings_max_per_run'")
    op.drop_table("publication_embeddings", schema="publications")
