"""restrict candidate_dois to in-perimeter source_publications

La vue `candidate_dois` alimente le cross-import par DOI et la résolution des
Registration Agencies (phase `resolve_ra`), délibérément sur le même pool.

Le bras `staging.doi` prenait tout DOI présent en staging, quel que soit son
périmètre : des records cross-importés hors-périmètre y injectaient leurs DOI,
qui déclenchaient d'autres cross-imports hors-périmètre (chaîne de propagation).
Mesure : ~88 % des DOI crossref/datacite cross-importés hors-périmètre ne
provenaient que de records hors-périmètre.

La vue est resserrée aux DOI portés par des publications `in_perimeter` :

- DOI primaires : `source_publications.doi` des publications in-périmètre
  (remplace le bras `staging.doi`) ;
- `related_dois` et DOI arXiv-dérivés : SP dont la publication est in-périmètre ;
- cibles de `publication_relations` : relations dont la `from_publication` est
  in-périmètre.

`in_perimeter` est la valeur matérialisée au run précédent ; les records
fraîchement extraits sont donc cross-importés au run suivant (pipeline
convergent). Coût de rappel mesuré : négligeable (~70 publications sur ~62 000).

Revision ID: c7f3a9e21d84
Revises: 4477146f78cf
Create Date: 2026-07-02 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7f3a9e21d84"
down_revision: str | Sequence[str] | None = "4477146f78cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_VIEW_PERIMETER = """
CREATE OR REPLACE VIEW public.candidate_dois AS
 SELECT sp.doi,
        sp.source
   FROM public.source_publications sp
   JOIN public.publications p ON p.id = sp.publication_id
  WHERE p.in_perimeter AND sp.doi IS NOT NULL
UNION
 SELECT d.value AS doi,
        sp.source
   FROM (public.source_publications sp
     JOIN public.publications p ON p.id = sp.publication_id)
     CROSS JOIN LATERAL jsonb_array_elements_text((sp.external_ids -> 'related_dois'::text)) d(value)
  WHERE p.in_perimeter
    AND jsonb_typeof((sp.external_ids -> 'related_dois'::text)) = 'array'::text
UNION
 SELECT pr.target_doi AS doi,
        NULL::public.source_type AS source
   FROM (public.publication_relations pr
     JOIN public.publications p ON p.id = pr.from_publication_id)
  WHERE p.in_perimeter AND pr.target_doi IS NOT NULL
UNION
 SELECT ('10.48550/arxiv.'::text || lower((sp.external_ids ->> 'arxiv_id'::text))) AS doi,
        sp.source
   FROM (public.source_publications sp
     JOIN public.publications p ON p.id = sp.publication_id)
  WHERE p.in_perimeter AND (sp.external_ids ->> 'arxiv_id'::text) IS NOT NULL;
"""

_VIEW_STAGING = """
CREATE OR REPLACE VIEW public.candidate_dois AS
 SELECT s.doi,
        s.source
   FROM public.staging s
  WHERE (s.doi IS NOT NULL)
UNION
 SELECT d.value AS doi,
        sp.source
   FROM (public.source_publications sp
     CROSS JOIN LATERAL jsonb_array_elements_text((sp.external_ids -> 'related_dois'::text)) d(value))
  WHERE (jsonb_typeof((sp.external_ids -> 'related_dois'::text)) = 'array'::text)
UNION
 SELECT pr.target_doi AS doi,
        NULL::public.source_type AS source
   FROM public.publication_relations pr
  WHERE (pr.target_doi IS NOT NULL)
UNION
 SELECT ('10.48550/arxiv.'::text || lower((sp.external_ids ->> 'arxiv_id'::text))) AS doi,
        sp.source
   FROM public.source_publications sp
  WHERE ((sp.external_ids ->> 'arxiv_id'::text) IS NOT NULL);
"""


def upgrade() -> None:
    op.execute(_VIEW_PERIMETER)


def downgrade() -> None:
    op.execute(_VIEW_STAGING)
