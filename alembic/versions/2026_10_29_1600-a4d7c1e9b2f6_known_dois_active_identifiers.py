"""Vue known_dois : DOI actifs de source_record_identifiers

Revision ID: a4d7c1e9b2f6
Revises: d9b3e6a1f5c2
Create Date: 2026-10-29 16:00:00.000000

Les DOI d'un enregistrement source sont ses DOI actifs de `source_record_identifiers`, tous rôles confondus.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4d7c1e9b2f6"
down_revision: str | Sequence[str] | None = "d9b3e6a1f5c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RELATIONS_AND_ARXIV = """
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
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW sources.known_dois AS
         SELECT i.id_value AS doi, sp.source, sp.publication_id
           FROM sources.source_records sp
           JOIN sources.source_record_identifiers i ON i.source_record_id = sp.id
          WHERE i.id_type = 'doi' AND i.removed_by IS NULL
        """
        + _RELATIONS_AND_ARXIV
    )
    op.execute("""
        COMMENT ON VIEW sources.known_dois IS 'Tous les DOI connus : DOI actifs des enregistrements sources, cibles des relations, DOI DataCite déduits des identifiants arXiv. publication_id est la publication de l''enregistrement source, ou la publication d''origine de la relation ; NULL pour un enregistrement source orphelin.'
    """)


def downgrade() -> None:
    op.execute(
        """
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
        """
        + _RELATIONS_AND_ARXIV
    )
    op.execute("""
        COMMENT ON VIEW sources.known_dois IS 'Tous les DOI connus : DOI des enregistrements sources, DOI liés, cibles des relations, DOI DataCite déduits des identifiants arXiv. publication_id est la publication de l''enregistrement source, ou la publication d''origine de la relation ; NULL pour un enregistrement source orphelin.'
    """)
