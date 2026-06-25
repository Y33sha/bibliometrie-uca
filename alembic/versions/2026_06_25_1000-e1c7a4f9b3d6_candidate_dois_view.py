"""candidate_dois : vue du pool unique de DOI candidats (cross-import + résolution RA)

Source de vérité unique des emplacements où un DOI peut apparaître : `staging.doi`,
`source_publications.external_ids.related_dois`, `publication_relations.target_doi`
(cible d'une relation, sans source → NULL) et les DOI DataCite déduits d'un arXiv id
(`10.48550/arxiv.<id>`). `source` est exposée en enum `source_type` (NULL pour les
relations) : les comparaisons `source = <param>` côté appelants restent enum=enum.

Consommée par `get_cross_import_dois` (filtre par target / RA / backoff) et par la
résolution de RA des préfixes (tous, sans exclusion de source) : un pool défini une
seule fois, impossible de re-diverger.

Revision ID: e1c7a4f9b3d6
Revises: c4e9a2f1b7d3
Create Date: 2026-06-25 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e1c7a4f9b3d6"
down_revision: str | Sequence[str] | None = "c4e9a2f1b7d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW candidate_dois AS
            SELECT s.doi, s.source
            FROM staging s
            WHERE s.doi IS NOT NULL
            UNION
            SELECT d AS doi, sp.source
            FROM source_publications sp
            CROSS JOIN LATERAL
                jsonb_array_elements_text(sp.external_ids -> 'related_dois') AS d
            WHERE jsonb_typeof(sp.external_ids -> 'related_dois') = 'array'
            UNION
            SELECT pr.target_doi AS doi, NULL::source_type AS source
            FROM publication_relations pr
            WHERE pr.target_doi IS NOT NULL
            UNION
            SELECT '10.48550/arxiv.' || lower(sp.external_ids ->> 'arxiv_id') AS doi,
                   sp.source
            FROM source_publications sp
            WHERE sp.external_ids ->> 'arxiv_id' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW candidate_dois")
