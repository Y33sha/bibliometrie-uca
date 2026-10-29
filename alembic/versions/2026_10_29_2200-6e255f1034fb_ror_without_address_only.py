"""Preuve ror de source_contribution_structures : ROR sans adresse seulement

Revision ID: 6e255f1034fb
Revises: a7d2e5c9f318
Create Date: 2026-10-29 22:00:00.000000

Dans `source_contribution_structures`, seul un ROR sans adresse est un indice : pour un ROR rattaché à une adresse, l'adresse fait autorité. `contribution_structures`, `publication_structures` et `publication_rors`, qui en dépendent, sont recréées à l'identique.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6e255f1034fb"
down_revision: str | Sequence[str] | None = "a7d2e5c9f318"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP = """
    DROP MATERIALIZED VIEW publications.publication_rors;
    DROP MATERIALIZED VIEW publications.publication_structures;
    DROP MATERIALIZED VIEW publications.contribution_structures;
    DROP MATERIALIZED VIEW sources.source_contribution_structures;
"""

_SOURCE_CONTRIBUTION_STRUCTURES = """
    CREATE MATERIALIZED VIEW sources.source_contribution_structures AS
    WITH RECURSIVE perimeter AS (
        SELECT ps.structure_id
        FROM structures.perimeter_structures ps
        WHERE ps.perimeter_id = (
            SELECT id FROM structures.perimeters
            WHERE code = (SELECT value #>> '{{}}' FROM ops.config WHERE key = 'perimeter_extraction')
        )
    ),
    hal_match AS (
        SELECT hs.hal_structure_id, s.id AS structure_id
        FROM ref.hal_structures hs
        JOIN structures.structures s ON s.ror_id = hs.ror_id
        UNION
        SELECT hal_structure_id, structure_id
        FROM ref.hal_structures
        WHERE structure_id IS NOT NULL
    ),
    hal_ancestors AS (
        SELECT child_id, parent_id AS ancestor_id, 1 AS depth
        FROM ref.hal_structure_relations
        UNION
        SELECT a.child_id, r.parent_id, a.depth + 1
        FROM hal_ancestors a
        JOIN ref.hal_structure_relations r ON r.child_id = a.ancestor_id
        WHERE a.depth < 10
    ),
    hal_direct AS (
        SELECT DISTINCT sah.source_contribution_id,
            COALESCE(al.hal_structure_id, sah.hal_structure_id) AS hal_structure_id
        FROM sources.source_contribution_hal_structures sah
        LEFT JOIN ref.hal_structure_aliases al ON al.alias_id = sah.hal_structure_id
    ),
    hal_lowest AS (
        SELECT source_contribution_id, hal_structure_id FROM hal_direct
        EXCEPT
        SELECT d.source_contribution_id, a.ancestor_id
        FROM hal_direct d
        JOIN hal_ancestors a ON a.child_id = d.hal_structure_id
    ),
    hal_walk AS (
        SELECT hal_structure_id AS origin_id, hal_structure_id, 0 AS depth
        FROM ref.hal_structures
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
    SELECT saa.source_contribution_id, ast.structure_id, 'address'::public.perimeter_evidence AS evidence
    FROM sources.source_contribution_addresses saa
    JOIN structures.address_structures ast ON ast.address_id = saa.address_id
    WHERE ast.is_confirmed IS DISTINCT FROM false
      AND ast.structure_id IN (SELECT structure_id FROM perimeter)
    UNION
    SELECT sar.source_contribution_id, s.id, 'ror'::public.perimeter_evidence
    FROM sources.source_contribution_rors sar
    JOIN structures.structures s ON s.ror_id = sar.ror_id
    WHERE s.id IN (SELECT structure_id FROM perimeter)
      AND {ror_condition}
    UNION
    SELECT l.source_contribution_id, r.structure_id, 'hal_structure'::public.perimeter_evidence
    FROM hal_lowest l
    JOIN hal_reach r ON r.origin_id = l.hal_structure_id
    UNION
    SELECT sa.id, s.id, 'thesis_institution'::public.perimeter_evidence
    FROM sources.source_records sp
    JOIN sources.source_contributions sa ON sa.source_record_id = sp.id
    JOIN structures.structures s ON (s.api_ids -> 'theses') ? (sp.source_extras ->> 'etablissement_ppn')
    WHERE sp.source = 'theses'
      AND s.id IN (SELECT structure_id FROM perimeter)
    UNION
    SELECT sa.id, ist.structure_id, 'thesis_partner'::public.perimeter_evidence
    FROM sources.source_records sp
    CROSS JOIN LATERAL jsonb_array_elements(sp.source_extras -> 'partenaires') partner(value)
    JOIN structures.idref_structures ist ON ist.idref_ppn = partner.value ->> 'ppn'
    JOIN sources.source_contributions sa
        ON sa.source_record_id = sp.id AND sa.roles && ARRAY['author'::text]
    WHERE sp.source = 'theses'
      AND ist.is_confirmed IS DISTINCT FROM false
      AND (ist.matched_form_id IS NOT NULL OR ist.is_confirmed)
      AND ist.structure_id IN (SELECT structure_id FROM perimeter)
    WITH DATA;

    CREATE UNIQUE INDEX source_contribution_structures_pkey
        ON sources.source_contribution_structures (source_contribution_id, structure_id, evidence);
    CREATE INDEX idx_source_contribution_structures_structure_id
        ON sources.source_contribution_structures (structure_id);
"""

_ROR_WITHOUT_ADDRESS = "sar.address_id IS NULL"

_ROR_WITH_ADDRESS_IN_PERIMETER = """(
        sar.address_id IS NULL
        OR EXISTS (
            SELECT 1 FROM structures.address_structures ast
            WHERE ast.address_id = sar.address_id
              AND ast.is_confirmed IS DISTINCT FROM false
              AND ast.structure_id IN (SELECT structure_id FROM perimeter)
        )
    )"""

_DEPENDENTS = """
    CREATE MATERIALIZED VIEW publications.contribution_structures AS
    SELECT DISTINCT m.contribution_id, scs.structure_id
    FROM sources.source_contribution_structures scs
    JOIN publications.aligned_source_contributions m ON m.source_contribution_id = scs.source_contribution_id
    JOIN publications.contributions g ON g.id = m.contribution_id
    JOIN persons.persons pe ON pe.id = g.person_id
    WHERE pe.exclusion IS NULL
    WITH DATA;

    CREATE UNIQUE INDEX contribution_structures_pkey
        ON publications.contribution_structures (contribution_id, structure_id);
    CREATE INDEX idx_contribution_structures_structure_id
        ON publications.contribution_structures (structure_id);

    CREATE MATERIALIZED VIEW publications.publication_structures AS
    SELECT DISTINCT g.publication_id, gs.structure_id
    FROM publications.contributions g
    JOIN publications.contribution_structures gs ON gs.contribution_id = g.id
    WHERE g.roles && ARRAY['author'::text]
    WITH DATA;

    CREATE UNIQUE INDEX publication_structures_publication_structure
        ON publications.publication_structures (publication_id, structure_id);
    CREATE INDEX idx_publication_structures_structure
        ON publications.publication_structures (structure_id);

    CREATE MATERIALIZED VIEW publications.publication_rors AS
    WITH RECURSIVE cited AS (
        SELECT c.publication_id, r.ror_id
        FROM publications.contributions c
        JOIN publications.aligned_source_contributions m ON m.contribution_id = c.id
        JOIN sources.source_contribution_rors r
            ON r.source_contribution_id = m.source_contribution_id
        LEFT JOIN persons.persons pe ON pe.id = c.person_id
        WHERE c.roles && ARRAY['author'::text]
          AND pe.exclusion IS DISTINCT FROM 'not_a_person'
        UNION
        SELECT ps.publication_id, s.ror_id
        FROM publications.publication_structures ps
        JOIN structures.structures s ON s.id = ps.structure_id
        WHERE s.ror_id IS NOT NULL
    ),
    lineage AS (
        SELECT publication_id, ror_id, true AS cited FROM cited
        UNION
        SELECT l.publication_id, rr.parent_ror_id, false
        FROM lineage l
        JOIN ref.ror_relations rr ON rr.child_ror_id = l.ror_id
    )
    SELECT publication_id, ror_id, bool_or(cited) AS cited
    FROM lineage
    GROUP BY publication_id, ror_id
    WITH DATA;

    CREATE UNIQUE INDEX publication_rors_pkey
        ON publications.publication_rors (publication_id, ror_id);
    CREATE INDEX idx_publication_rors_ror ON publications.publication_rors (ror_id);
"""


def _recreate(ror_condition: str) -> None:
    op.execute(_DROP)
    op.execute(_SOURCE_CONTRIBUTION_STRUCTURES.format(ror_condition=ror_condition))
    op.execute(_DEPENDENTS)


def upgrade() -> None:
    _recreate(_ROR_WITHOUT_ADDRESS)


def downgrade() -> None:
    _recreate(_ROR_WITH_ADDRESS_IN_PERIMETER)
