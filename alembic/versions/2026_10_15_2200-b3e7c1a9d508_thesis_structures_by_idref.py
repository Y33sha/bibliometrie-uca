"""Structures d'une thèse par le PPN IdRef

- `structures.idref_structures` rattache le PPN IdRef d'un laboratoire partenaire de thèse à une structure interne, sur le modèle de `address_structures` : forme de nom à l'origine, confirmation.
- Le type `perimeter_evidence` gagne la valeur `thesis_partner`.
- `source_authorship_structures` gagne deux branches de thèse : l'établissement de soutenance, reconnu par son PPN dans `api_ids.theses`, rattache toutes les signatures de la notice theses.fr (`thesis_institution`) ; un laboratoire partenaire, reconnu par son PPN dans `idref_structures`, rattache la signature du doctorant (`thesis_partner`). `authorship_structures` et `publication_structures` sont recréées à l'identique.

Revision ID: b3e7c1a9d508
Revises: d7f2b9e4a613
Create Date: 2026-10-15 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b3e7c1a9d508"
down_revision: str | Sequence[str] | None = "d7f2b9e4a613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDREF_STRUCTURES = """
    CREATE TABLE structures.idref_structures (
        idref_ppn text NOT NULL,
        structure_id integer NOT NULL REFERENCES structures.structures ON DELETE CASCADE,
        matched_form_id integer REFERENCES structures.structure_name_forms ON DELETE SET NULL,
        is_confirmed boolean,
        CONSTRAINT idref_structures_pkey PRIMARY KEY (idref_ppn, structure_id)
    );
    COMMENT ON TABLE structures.idref_structures IS
        'Structure interne d''un PPN IdRef de laboratoire partenaire de thèse : détectée par une forme de nom (matched_form_id), confirmée ou infirmée par l''administration (is_confirmed).';
    CREATE INDEX ix_idref_structures_structure_id ON structures.idref_structures (structure_id);
"""


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
    -- Structures internes de chaque structure HAL : par le ROR, par la correspondance explicite.
    hal_match AS (
        SELECT hs.hal_structure_id, s.id AS structure_id
        FROM ref.hal_structures hs
        JOIN structures.structures s ON s.ror_id = hs.ror_id
        UNION
        SELECT hal_structure_id, structure_id FROM ref.hal_structures WHERE structure_id IS NOT NULL
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
    UNION
    SELECT sa.id, s.id, 'thesis_institution'::public.perimeter_evidence
    FROM sources.source_publications sp
    JOIN sources.source_authorships sa ON sa.source_publication_id = sp.id
    JOIN structures.structures s ON s.api_ids -> 'theses' ? (sp.meta ->> 'etablissement_ppn')
    WHERE sp.source = 'theses' AND s.id IN (SELECT structure_id FROM perimeter)
    UNION
    SELECT sa.id, ist.structure_id, 'thesis_partner'::public.perimeter_evidence
    FROM sources.source_publications sp
    CROSS JOIN LATERAL jsonb_array_elements(sp.meta -> 'partenaires') partner
    JOIN structures.idref_structures ist ON ist.idref_ppn = partner ->> 'ppn'
    JOIN sources.source_authorships sa
        ON sa.source_publication_id = sp.id AND sa.roles && ARRAY['author']::text[]
    WHERE sp.source = 'theses'
      AND ist.is_confirmed IS DISTINCT FROM false
      AND (ist.matched_form_id IS NOT NULL OR ist.is_confirmed)
      AND ist.structure_id IN (SELECT structure_id FROM perimeter)
    WITH DATA;

    CREATE UNIQUE INDEX source_authorship_structures_pkey
        ON sources.source_authorship_structures (source_authorship_id, structure_id, evidence);
"""

_SOURCE_AUTHORSHIP_STRUCTURES_PREVIOUS = f"""
    CREATE MATERIALIZED VIEW sources.source_authorship_structures AS
    WITH RECURSIVE {_PERIMETER},
    -- Structures internes de chaque structure HAL : par le ROR, par la correspondance explicite.
    hal_match AS (
        SELECT hs.hal_structure_id, s.id AS structure_id
        FROM ref.hal_structures hs
        JOIN structures.structures s ON s.ror_id = hs.ror_id
        UNION
        SELECT hal_structure_id, structure_id FROM ref.hal_structures WHERE structure_id IS NOT NULL
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
    WHERE a.roles && ARRAY['author']::text[]
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
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE public.perimeter_evidence ADD VALUE IF NOT EXISTS 'thesis_partner'")
    op.execute(_IDREF_STRUCTURES)
    op.execute(_DROP)
    op.execute(_SOURCE_AUTHORSHIP_STRUCTURES)
    op.execute(_DEPENDENT_STRUCTURE_VIEWS)


def downgrade() -> None:
    op.execute(_DROP)
    op.execute(_SOURCE_AUTHORSHIP_STRUCTURES_PREVIOUS)
    op.execute(_DEPENDENT_STRUCTURE_VIEWS)
    op.execute("DROP TABLE structures.idref_structures")
    # PostgreSQL ne retire pas une valeur d'enum : `thesis_partner` reste dans `perimeter_evidence`.
