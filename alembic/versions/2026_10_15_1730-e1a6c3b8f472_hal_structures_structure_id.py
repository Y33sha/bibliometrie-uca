"""Structure interne d'une structure HAL

`ref.hal_structures.structure_id` rattache une structure HAL à une structure interne, quand leur ROR ne les relie pas. Les correspondances de `structures.api_ids->'hal'` y sont recopiées, puis la clé `hal` est retirée de `api_ids`.

Revision ID: e1a6c3b8f472
Revises: b5d9f3a7c128
Create Date: 2026-10-15 17:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e1a6c3b8f472"
down_revision: str | Sequence[str] | None = "b5d9f3a7c128"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE ref.hal_structures
            ADD COLUMN structure_id integer REFERENCES structures.structures ON DELETE SET NULL;
        CREATE INDEX ix_hal_structures_structure_id ON ref.hal_structures (structure_id);
        COMMENT ON TABLE ref.hal_structures IS
            'Structures du référentiel HAL (ref/structure). Référentiel externe : son ROR, ou structure_id, le relie au référentiel interne.';

        UPDATE ref.hal_structures h
        SET structure_id = m.structure_id
        FROM (
            SELECT hal.value::int AS hal_structure_id, min(s.id) AS structure_id
            FROM structures.structures s
            CROSS JOIN LATERAL jsonb_array_elements_text(s.api_ids -> 'hal') hal(value)
            WHERE s.api_ids ? 'hal' AND hal.value ~ '^[0-9]+$'
            GROUP BY 1
        ) m
        WHERE m.hal_structure_id = h.hal_structure_id;

        UPDATE structures.structures
        SET api_ids = nullif(api_ids - 'hal', '{}'::jsonb)
        WHERE api_ids ? 'hal';
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE structures.structures s
        SET api_ids = coalesce(s.api_ids, '{}'::jsonb) || jsonb_build_object('hal', m.ids)
        FROM (
            SELECT structure_id, jsonb_agg(hal_structure_id::text ORDER BY hal_structure_id) AS ids
            FROM ref.hal_structures
            WHERE structure_id IS NOT NULL
            GROUP BY structure_id
        ) m
        WHERE m.structure_id = s.id;

        ALTER TABLE ref.hal_structures DROP COLUMN structure_id;
        COMMENT ON TABLE ref.hal_structures IS
            'Structures du référentiel HAL (ref/structure). Référentiel externe : son ROR, ou structures.api_ids->''hal'', le relie au référentiel interne.';
    """)
