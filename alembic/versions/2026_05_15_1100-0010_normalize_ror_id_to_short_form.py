"""structures.ror_id : normaliser vers la forme courte (9-char nu)

Le RorId est désormais un VO côté domain dont la forme canonique est
l'identifiant 9-char nu (ex. ``02feahw73``), analogue à ORCID. L'URL
``https://ror.org/<id>`` reste possible à l'affichage mais n'est plus
la forme de stockage. Cette migration aligne les données existantes
(préfixe URL strippé) pour qu'elles passent la validation du VO lors
de l'hydratation.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-15 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Strip des préfixes URL connus. lower() pour matcher la forme du VO.
    op.execute(
        """
        UPDATE structures
        SET ror_id = lower(
            regexp_replace(
                ror_id,
                '^(https?://)?ror\\.org/',
                '',
                'i'
            )
        )
        WHERE ror_id IS NOT NULL
          AND ror_id ~* '^(https?://)?ror\\.org/'
        """
    )


def downgrade() -> None:
    # Réintroduit le préfixe URL canonique pour toute valeur 9-char.
    op.execute(
        """
        UPDATE structures
        SET ror_id = 'https://ror.org/' || ror_id
        WHERE ror_id IS NOT NULL
          AND ror_id ~ '^0[0-9a-hjkmnp-z]{8}$'
        """
    )
