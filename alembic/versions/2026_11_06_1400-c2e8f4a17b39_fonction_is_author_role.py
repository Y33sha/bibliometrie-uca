"""Fonction is_author_role : rôles d'auteur, auteur et inventeur

Revision ID: c2e8f4a17b39
Revises: 9b4e7d2c1a85
Create Date: 2026-11-06 14:00:00.000000

La fonction `is_author_role(roles)` reprend les rôles d'auteur du domaine (`AUTHOR_ROLES`) : l'auteur d'un document, l'inventeur d'un brevet. `publication_structures` et `publication_rors` sont recréées pour l'appeler.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2e8f4a17b39"
down_revision: str | Sequence[str] | None = "9b4e7d2c1a85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTION = """
    CREATE FUNCTION public.is_author_role(roles text[]) RETURNS boolean
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        RETURN roles && ARRAY['author', 'inventor']::text[];
"""

_DROP_VIEWS = """
    DROP MATERIALIZED VIEW publications.publication_rors;
    DROP MATERIALIZED VIEW publications.publication_structures;
"""

_VIEWS = """
    CREATE MATERIALIZED VIEW publications.publication_structures AS
    SELECT DISTINCT g.publication_id, gs.structure_id
    FROM publications.contributions g
    JOIN publications.contribution_structures gs ON gs.contribution_id = g.id
    WHERE {author_role}
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
        WHERE {author_role_c}
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


def upgrade() -> None:
    op.execute(_FUNCTION)
    op.execute(_DROP_VIEWS)
    op.execute(
        _VIEWS.format(
            author_role="public.is_author_role(g.roles)",
            author_role_c="public.is_author_role(c.roles)",
        )
    )


def downgrade() -> None:
    op.execute(_DROP_VIEWS)
    op.execute(
        _VIEWS.format(
            author_role="g.roles && ARRAY['author'::text]",
            author_role_c="c.roles && ARRAY['author'::text]",
        )
    )
    op.execute("DROP FUNCTION public.is_author_role(text[])")
