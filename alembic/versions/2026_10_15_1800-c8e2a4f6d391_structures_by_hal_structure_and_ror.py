"""Branches `hal_structure` et `ror` de `source_authorship_structures`

La vue associe une signature aux structures du périmètre d'extraction qu'elle atteint, par trois indices :

- `address` : une adresse de la signature est rattachée à la structure, lien non infirmé ;
- `ror` : un ROR de la signature est celui de la structure. Un ROR posé sur une adresse sans structure du périmètre est écarté ;
- `hal_structure` : une structure HAL de la signature correspond à la structure, par son ROR ou par `structures.api_ids->'hal'`. Un alias se ramène à sa structure conservée. Parmi les structures HAL d'une signature, seules comptent les plus basses de la hiérarchie. Une structure sans correspondance remonte à ses parents HAL, jusqu'à la première qui en a une.

`authorship_structures` et `publication_structures`, qui en dépendent, sont recréées à l'identique.

Revision ID: c8e2a4f6d391
Revises: b5d9f3a7c128
Create Date: 2026-10-15 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8e2a4f6d391"
down_revision: str | Sequence[str] | None = "b5d9f3a7c128"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DROP = """
    DROP MATERIALIZED VIEW publications.publication_structures;
    DROP MATERIALIZED VIEW publications.authorship_structures;
    DROP MATERIALIZED VIEW sources.source_authorship_structures;
"""

_PERIMETER = """
    perimeter AS (
        SELECT ps.structure_id
        FROM structures.perimeter_structures ps
        WHERE ps.perimeter_id = (
            SELECT perimeters.id FROM structures.perimeters
            WHERE perimeters.code = (
                SELECT config.value #>> '{}' FROM ops.config WHERE config.key = 'perimeter_extraction'
            )
        )
    )
"""

_ADDRESS_BRANCH = """
    SELECT saa.source_authorship_id, ast.structure_id, 'address'::public.perimeter_evidence AS evidence
    FROM sources.source_authorship_addresses saa
    JOIN structures.address_structures ast ON ast.address_id = saa.address_id
    WHERE ast.is_confirmed IS DISTINCT FROM false
      AND ast.structure_id IN (SELECT structure_id FROM perimeter)
"""

_SOURCE_AUTHORSHIP_STRUCTURES = f"""
    CREATE MATERIALIZED VIEW sources.source_authorship_structures AS
    WITH RECURSIVE {_PERIMETER},
    -- Structures internes de chaque structure HAL : par le ROR, par la liste de api_ids.
    hal_match AS (
        SELECT hs.hal_structure_id, s.id AS structure_id
        FROM ref.hal_structures hs
        JOIN structures.structures s ON s.ror_id = hs.ror_id
        UNION
        SELECT h.value::int, s.id
        FROM structures.structures s
        CROSS JOIN LATERAL jsonb_array_elements_text(s.api_ids -> 'hal') h(value)
        WHERE s.api_ids ? 'hal' AND h.value ~ '^[0-9]+$'
    ),
    hal_ancestors AS (
        SELECT child_id, parent_id AS ancestor_id, 1 AS depth FROM ref.hal_structure_relations
        UNION
        SELECT a.child_id, r.parent_id, a.depth + 1
        FROM hal_ancestors a
        JOIN ref.hal_structure_relations r ON r.child_id = a.ancestor_id
        WHERE a.depth < 10
    ),
    hal_direct AS (
        SELECT DISTINCT sah.source_authorship_id, coalesce(al.hal_structure_id, sah.hal_structure_id) AS hal_structure_id
        FROM sources.source_authorship_hal_structures sah
        LEFT JOIN ref.hal_structure_aliases al ON al.alias_id = sah.hal_structure_id
    ),
    -- Structures les plus basses d'une signature : ses structures HAL, moins les ancêtres de ses autres structures.
    hal_lowest AS (
        SELECT source_authorship_id, hal_structure_id FROM hal_direct
        EXCEPT
        SELECT d.source_authorship_id, a.ancestor_id
        FROM hal_direct d
        JOIN hal_ancestors a ON a.child_id = d.hal_structure_id
    ),
    -- Remontée des parents HAL de chaque structure, tant qu'elle est sans correspondance interne.
    hal_walk AS (
        SELECT hal_structure_id AS origin_id, hal_structure_id, 0 AS depth FROM ref.hal_structures
        UNION
        SELECT w.origin_id, r.parent_id, w.depth + 1
        FROM hal_walk w
        JOIN ref.hal_structure_relations r ON r.child_id = w.hal_structure_id
        WHERE w.depth < 10
          AND NOT EXISTS (SELECT 1 FROM hal_match m WHERE m.hal_structure_id = w.hal_structure_id)
    ),
    hal_reach AS (
        SELECT DISTINCT w.origin_id, m.structure_id
        FROM hal_walk w
        JOIN hal_match m ON m.hal_structure_id = w.hal_structure_id
        WHERE m.structure_id IN (SELECT structure_id FROM perimeter)
    )
    {_ADDRESS_BRANCH}
    UNION
    SELECT sar.source_authorship_id, s.id, 'ror'::public.perimeter_evidence
    FROM sources.source_authorship_rors sar
    JOIN structures.structures s ON s.ror_id = sar.ror_id
    WHERE s.id IN (SELECT structure_id FROM perimeter)
      AND (
          sar.address_id IS NULL
          OR EXISTS (
              SELECT 1 FROM structures.address_structures ast
              WHERE ast.address_id = sar.address_id
                AND ast.is_confirmed IS DISTINCT FROM false
                AND ast.structure_id IN (SELECT structure_id FROM perimeter)
          )
      )
    UNION
    SELECT l.source_authorship_id, r.structure_id, 'hal_structure'::public.perimeter_evidence
    FROM hal_lowest l
    JOIN hal_reach r ON r.origin_id = l.hal_structure_id
    WITH DATA;

    CREATE UNIQUE INDEX source_authorship_structures_pkey
        ON sources.source_authorship_structures (source_authorship_id, structure_id, evidence);
"""

_SOURCE_AUTHORSHIP_STRUCTURES_DOWNGRADE = f"""
    CREATE MATERIALIZED VIEW sources.source_authorship_structures AS
    WITH {_PERIMETER}
    {_ADDRESS_BRANCH}
    WITH DATA;

    CREATE UNIQUE INDEX source_authorship_structures_pkey
        ON sources.source_authorship_structures (source_authorship_id, structure_id, evidence);
"""

_DEPENDENT_STRUCTURE_VIEWS = """
    CREATE INDEX idx_source_authorship_structures_structure_id
        ON sources.source_authorship_structures (structure_id);

    CREATE MATERIALIZED VIEW publications.authorship_structures AS
    SELECT DISTINCT a.id AS authorship_id, sas.structure_id
    FROM sources.source_authorship_structures sas
    JOIN sources.source_authorships sa ON sa.id = sas.source_authorship_id
    JOIN sources.source_publications sp ON sp.id = sa.source_publication_id
    JOIN publications.authorships a ON a.publication_id = sp.publication_id AND a.person_id = sa.person_id
    WHERE NOT EXISTS (
        SELECT 1 FROM persons.persons pe WHERE pe.id = a.person_id AND pe.exclusion IS NOT NULL
    )
    WITH DATA;

    CREATE MATERIALIZED VIEW publications.publication_structures AS
    SELECT DISTINCT a.publication_id, aus.structure_id
    FROM publications.authorships a
    JOIN publications.authorship_structures aus ON aus.authorship_id = a.id
    WITH DATA;

    CREATE UNIQUE INDEX authorship_structures_pkey
        ON publications.authorship_structures (authorship_id, structure_id);
    CREATE INDEX idx_authorship_structures_structure_id
        ON publications.authorship_structures (structure_id);
    CREATE UNIQUE INDEX publication_structures_pub_struct
        ON publications.publication_structures (publication_id, structure_id);
    CREATE INDEX idx_publication_structures_structure
        ON publications.publication_structures (structure_id);
"""


def upgrade() -> None:
    op.execute(_DROP)
    op.execute(_SOURCE_AUTHORSHIP_STRUCTURES)
    op.execute(_DEPENDENT_STRUCTURE_VIEWS)


def downgrade() -> None:
    op.execute(_DROP)
    op.execute(_SOURCE_AUTHORSHIP_STRUCTURES_DOWNGRADE)
    op.execute(_DEPENDENT_STRUCTURE_VIEWS)
