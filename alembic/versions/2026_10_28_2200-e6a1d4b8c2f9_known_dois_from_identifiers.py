"""Vue known_dois lue dans source_record_identifiers

Revision ID: e6a1d4b8c2f9
Revises: c4f9a2e7b1d3
Create Date: 2026-10-28 22:00:00.000000

Les DOI liés d'un enregistrement source sont ses DOI actifs autres que son DOI d'avant correction. Le DOI DataCite déduit de l'identifiant arXiv part de l'identifiant arXiv actif de rôle le plus fort, puis de plus petite valeur. Ce sont les valeurs qu'`external_ids` retient.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e6a1d4b8c2f9"
down_revision: str | Sequence[str] | None = "c4f9a2e7b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW sources.known_dois AS
         SELECT sp.doi, sp.source, sp.publication_id
           FROM sources.source_records sp
          WHERE sp.doi IS NOT NULL
        UNION
         SELECT i.id_value AS doi, sp.source, sp.publication_id
           FROM sources.source_records sp
           JOIN sources.source_record_identifiers i ON i.source_record_id = sp.id
          WHERE i.id_type = 'doi' AND i.removed_by IS NULL
            AND i.id_value IS DISTINCT FROM CASE WHEN sp.corrections -> 'doi' ? 'raw'
                THEN sp.corrections -> 'doi' ->> 'raw' ELSE sp.doi END
        UNION
         SELECT pr.target_doi AS doi, NULL::public.source_type AS source,
                pr.from_publication_id AS publication_id
           FROM publications.publication_relations pr
          WHERE pr.target_doi IS NOT NULL
        UNION
         SELECT '10.48550/arxiv.' || lower(i.id_value) AS doi, sp.source, sp.publication_id
           FROM sources.source_records sp
           JOIN sources.source_record_identifiers i ON i.source_record_id = sp.id
          WHERE i.id_type = 'arxiv_id' AND i.removed_by IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM sources.source_record_identifiers x
                WHERE x.source_record_id = i.source_record_id AND x.id_type = i.id_type
                  AND x.removed_by IS NULL
                  AND (CASE x.role WHEN 'primary' THEN 1 WHEN 'derived' THEN 2
                                   WHEN 'secondary' THEN 3 WHEN 'related' THEN 4 END,
                       x.id_value COLLATE "C")
                    < (CASE i.role WHEN 'primary' THEN 1 WHEN 'derived' THEN 2
                                   WHEN 'secondary' THEN 3 WHEN 'related' THEN 4 END,
                       i.id_value COLLATE "C")
            );
    """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW sources.known_dois AS
         SELECT sp.doi, sp.source, sp.publication_id
           FROM sources.source_records sp
          WHERE sp.doi IS NOT NULL
        UNION
         SELECT d.value AS doi, sp.source, sp.publication_id
           FROM sources.source_records sp
           CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids -> 'related_dois') d(value)
          WHERE jsonb_typeof(sp.external_ids -> 'related_dois') = 'array'
        UNION
         SELECT pr.target_doi AS doi, NULL::public.source_type AS source,
                pr.from_publication_id AS publication_id
           FROM publications.publication_relations pr
          WHERE pr.target_doi IS NOT NULL
        UNION
         SELECT '10.48550/arxiv.' || lower(sp.external_ids ->> 'arxiv_id') AS doi, sp.source,
                sp.publication_id
           FROM sources.source_records sp
          WHERE (sp.external_ids ->> 'arxiv_id') IS NOT NULL;
    """)
