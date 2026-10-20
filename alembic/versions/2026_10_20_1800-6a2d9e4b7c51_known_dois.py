"""Vue known_dois : tous les DOI connus, dont candidate_dois retient ceux du périmètre

Revision ID: 6a2d9e4b7c51
Revises: 3c9a7e5d1f20
Create Date: 2026-10-20 18:00:00.000000

`sources.known_dois` réunit les DOI des notices, leurs DOI liés, les cibles des relations et les DOI DataCite déduits des identifiants arXiv, avec la publication de chacun. `sources.candidate_dois` en retient les DOI des publications du périmètre ; elle rend les mêmes lignes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6a2d9e4b7c51"
down_revision: str | Sequence[str] | None = "3c9a7e5d1f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KNOWN_DOIS = """
    CREATE VIEW sources.known_dois AS
     SELECT sp.doi, sp.source, sp.publication_id
       FROM sources.source_publications sp
      WHERE sp.doi IS NOT NULL
    UNION
     SELECT d.value AS doi, sp.source, sp.publication_id
       FROM sources.source_publications sp
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
       FROM sources.source_publications sp
      WHERE (sp.external_ids ->> 'arxiv_id') IS NOT NULL;

    COMMENT ON VIEW sources.known_dois IS 'Tous les DOI connus : DOI des notices, DOI liés, cibles des relations, DOI DataCite déduits des identifiants arXiv. publication_id est la publication de la notice, ou la publication d''origine de la relation ; NULL pour une notice orpheline.';
"""

_CANDIDATE_DOIS = """
    CREATE OR REPLACE VIEW sources.candidate_dois AS
     SELECT DISTINCT k.doi, k.source
       FROM sources.known_dois k
       JOIN publications.publications p ON p.id = k.publication_id
      WHERE p.in_perimeter;
"""

_CANDIDATE_DOIS_STANDALONE = """
    CREATE OR REPLACE VIEW sources.candidate_dois AS
     SELECT sp.doi, sp.source
       FROM sources.source_publications sp
       JOIN publications.publications p ON p.id = sp.publication_id
      WHERE p.in_perimeter AND sp.doi IS NOT NULL
    UNION
     SELECT d.value AS doi, sp.source
       FROM sources.source_publications sp
       JOIN publications.publications p ON p.id = sp.publication_id
       CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids -> 'related_dois') d(value)
      WHERE p.in_perimeter AND jsonb_typeof(sp.external_ids -> 'related_dois') = 'array'
    UNION
     SELECT pr.target_doi AS doi, NULL::public.source_type AS source
       FROM publications.publication_relations pr
       JOIN publications.publications p ON p.id = pr.from_publication_id
      WHERE p.in_perimeter AND pr.target_doi IS NOT NULL
    UNION
     SELECT '10.48550/arxiv.' || lower(sp.external_ids ->> 'arxiv_id') AS doi, sp.source
       FROM sources.source_publications sp
       JOIN publications.publications p ON p.id = sp.publication_id
      WHERE p.in_perimeter AND (sp.external_ids ->> 'arxiv_id') IS NOT NULL;
"""


def upgrade() -> None:
    op.execute(_KNOWN_DOIS)
    op.execute(_CANDIDATE_DOIS)


def downgrade() -> None:
    op.execute(_CANDIDATE_DOIS_STANDALONE)
    op.execute("DROP VIEW sources.known_dois")
