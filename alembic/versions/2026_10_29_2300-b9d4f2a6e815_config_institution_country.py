"""Pays de l'établissement

`institution_country` contient le pays de l'établissement, code ISO 3166-1 en minuscules. La valeur initiale est le pays le plus fréquent parmi les organisations ROR des structures du périmètre des personnes (à défaut, du périmètre d'extraction), et `fr` sans organisation ROR.

Revision ID: b9d4f2a6e815
Revises: 6e255f1034fb
Create Date: 2026-10-29 23:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b9d4f2a6e815"
down_revision: str | Sequence[str] | None = "6e255f1034fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO ops.config (key, value, description)
        SELECT 'institution_country',
               to_jsonb(COALESCE((
                   SELECT lower(r.country_code::text)
                   FROM structures.perimeters p
                   JOIN structures.perimeter_structures ps ON ps.perimeter_id = p.id
                   JOIN structures.structures s ON s.id = ps.structure_id
                   JOIN ref.ror_organizations r ON r.ror_id = s.ror_id
                   WHERE p.code = COALESCE(
                       (SELECT NULLIF(value #>> '{}', '') FROM ops.config WHERE key = 'perimeter_persons'),
                       (SELECT value #>> '{}' FROM ops.config WHERE key = 'perimeter_extraction')
                   )
                   GROUP BY 1
                   ORDER BY count(*) DESC, 1
                   LIMIT 1
               ), 'fr')),
               'Pays de l''établissement, code ISO 3166-1. Une publication co-affiliée à un autre pays est une collaboration internationale.'
        ON CONFLICT (key) DO NOTHING
    """)
    op.execute(
        "ALTER TABLE ops.config ADD CONSTRAINT config_institution_country_is_code CHECK ("
        "  key <> 'institution_country' OR (jsonb_typeof(value) = 'string'"
        "  AND value #>> '{}' ~ '^[a-z]{2}$'"
        "  AND value #>> '{}' <> 'xx'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ops.config DROP CONSTRAINT config_institution_country_is_code")
    op.execute("DELETE FROM ops.config WHERE key = 'institution_country'")
