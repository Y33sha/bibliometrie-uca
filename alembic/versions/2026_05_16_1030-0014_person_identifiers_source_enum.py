"""person_identifiers.source : vestiges → enum identifier_origin + NOT NULL

Doctrine actuelle (cf. `application/persons.py:add_identifiers_from_authorships`) :
seules `'manual'` (route admin) et `'auto'` (pipeline) sont écrites.
Les valeurs `'hal'`, `'openalex'`, etc. qui peuvent traîner en base sont
des vestiges d'un usage abandonné (suivi de la source d'origine, jugé
non exploitable et retiré).

Migration :
1. Normaliser : vestiges + NULL → `'auto'` (origine pipeline par défaut)
2. Créer l'enum `identifier_origin` (`manual`, `auto`)
3. Convertir la colonne + NOT NULL (la sémantique exige une origine)

Pas de confusion avec l'enum `source_type` (sources biblio HAL/OA/…),
d'où le nom dédié `identifier_origin`.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-16 10:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE person_identifiers
        SET source = 'auto'
        WHERE source IS NULL OR source NOT IN ('manual', 'auto')
        """
    )
    op.execute("CREATE TYPE identifier_origin AS ENUM ('manual', 'auto')")
    op.execute(
        """
        ALTER TABLE person_identifiers
        ALTER COLUMN source TYPE identifier_origin
        USING source::identifier_origin,
        ALTER COLUMN source SET NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE person_identifiers
        ALTER COLUMN source TYPE text
        USING source::text,
        ALTER COLUMN source DROP NOT NULL
        """
    )
    op.execute("DROP TYPE identifier_origin")
