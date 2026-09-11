"""failed_lookups : journal des recherches infructueuses, par type d'identifiant

`doi_lookups` devient `failed_lookups`, avec une colonne `id_type` (`doi`, `hal_id`, `nnt`) : la phase fetch_missing y inscrit les DOI, hal-ids et NNT cherchés en vain. Les lignes `staging` marquées introuvables (hal-ids absents de HAL, sans `source_publications`) y sont versées avec `next_retry` NULL, puis supprimées. `staging.not_found_at` et sa contrainte disparaissent.

Revision ID: c6e1a93f5b28
Revises: b5d0f28c4a37
Create Date: 2026-09-11 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c6e1a93f5b28"
down_revision: str | Sequence[str] | None = "b5d0f28c4a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
CREATE TABLE public.failed_lookups (
    source public.source_type NOT NULL,
    id_type text NOT NULL,
    id_value text NOT NULL,
    not_found_at timestamp with time zone NOT NULL,
    next_retry timestamp with time zone,
    CONSTRAINT failed_lookups_pkey PRIMARY KEY (source, id_type, id_value),
    CONSTRAINT failed_lookups_id_type_check
        CHECK (id_type = ANY (ARRAY['doi'::text, 'hal_id'::text, 'nnt'::text]))
);

COMMENT ON TABLE public.failed_lookups IS 'Identifiants cherchés en vain dans une source par la phase fetch_missing. next_retry porte la date de la prochaine tentative. Il est NULL quand l''identifiant est natif de la source (le DOI pour Crossref et DataCite, le hal-id pour HAL) : l''échec est alors définitif.';

INSERT INTO public.failed_lookups (source, id_type, id_value, not_found_at, next_retry)
SELECT source, 'doi', doi, not_found_at, next_retry
FROM public.doi_lookups;

DROP TABLE public.doi_lookups;

INSERT INTO public.failed_lookups (source, id_type, id_value, not_found_at, next_retry)
SELECT s.source, 'hal_id', s.source_id, s.not_found_at, NULL
FROM public.staging s
WHERE s.source = 'hal'
  AND s.not_found_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.source_publications sp WHERE sp.staging_id = s.id);

DELETE FROM public.staging s
WHERE s.not_found_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.source_publications sp WHERE sp.staging_id = s.id);

ALTER TABLE public.staging DROP CONSTRAINT staging_not_found_at_implies_processed;
ALTER TABLE public.staging DROP COLUMN not_found_at;

COMMENT ON TABLE public.staging IS 'Documents moissonnés, en transit vers les tables sources. Deux états : à traiter (processed FALSE, raw_data porte le payload de la source), normalisée (processed TRUE, raw_data vidé).';
"""

_DOWNGRADE = """
ALTER TABLE public.staging ADD COLUMN not_found_at timestamp with time zone;

INSERT INTO public.staging (source, source_id, raw_data, processed, not_found_at, entry_mode)
SELECT source, id_value, '{}'::jsonb, TRUE, not_found_at, 'cross_import_hal'
FROM public.failed_lookups
WHERE source = 'hal' AND id_type = 'hal_id'
ON CONFLICT (source, source_id) DO NOTHING;

ALTER TABLE public.staging
    ADD CONSTRAINT staging_not_found_at_implies_processed CHECK (((not_found_at IS NULL) OR processed));

COMMENT ON TABLE public.staging IS 'Documents moissonnés, en transit vers les tables sources. Trois états : à traiter (processed FALSE, raw_data porte le payload de la source), normalisée (processed TRUE, raw_data vidé), introuvable (processed TRUE, not_found_at horodaté, raw_data jamais peuplé). Le dernier est posé par la phase fetch_missing quand HAL ne rend pas un document demandé par hal-id ou NNT.';

CREATE TABLE public.doi_lookups (
    source public.source_type NOT NULL,
    doi text NOT NULL,
    not_found_at timestamp with time zone NOT NULL,
    next_retry timestamp with time zone,
    CONSTRAINT doi_lookups_pkey PRIMARY KEY (source, doi)
);

INSERT INTO public.doi_lookups (source, doi, not_found_at, next_retry)
SELECT source, id_value, not_found_at, next_retry
FROM public.failed_lookups
WHERE id_type = 'doi';

DROP TABLE public.failed_lookups;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
