"""matview person_identifier_keys : lire les identifiants via author_identifying_keys

La matview `person_identifier_keys` matérialise les triplets `(person_id, id_type, id_value)` observés sur les signatures rattachées, pour la file de triage admin « conflits d'identifiant » (personnes distinctes au même identifiant brut). Elle lit les identifiants via `source_authorships` → `author_identifying_keys` (join par `identity_id`) au lieu de la colonne `source_authorships.person_identifiers` déménagée. Comportement identique ; l'`unnest` du jsonb porte désormais sur ~645 k identités et non sur les 19 M signatures.

Recréée `WITH NO DATA` (peuplée par le `REFRESH` du pipeline, comme avant) avec ses deux index (l'unique est requis par le `REFRESH … CONCURRENTLY`).

Revision ID: d7a2f6b3e918
Revises: c4e8b1a6d093
Create Date: 2026-07-02 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7a2f6b3e918"
down_revision: str | Sequence[str] | None = "c4e8b1a6d093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
DROP MATERIALIZED VIEW public.person_identifier_keys;

CREATE MATERIALIZED VIEW public.person_identifier_keys AS
 SELECT DISTINCT sa.person_id,
        k.k AS id_type,
        (aik.person_identifiers ->> k.k) AS id_value
   FROM public.source_authorships sa
     JOIN public.author_identifying_keys aik ON aik.id = sa.identity_id
     CROSS JOIN unnest(ARRAY['orcid'::text, 'idref'::text, 'hal_person_id'::text, 'idhal'::text]) k(k)
  WHERE sa.person_id IS NOT NULL
    AND aik.person_identifiers ? k.k
    AND (aik.person_identifiers ->> k.k) !~~ '%_dubious'::text
 WITH NO DATA;

CREATE UNIQUE INDEX idx_person_identifier_keys_uq
    ON public.person_identifier_keys USING btree (person_id, id_type, id_value);
CREATE INDEX idx_person_identifier_keys_value
    ON public.person_identifier_keys USING btree (id_type, id_value);
"""

_DOWNGRADE = """
DROP MATERIALIZED VIEW public.person_identifier_keys;

CREATE MATERIALIZED VIEW public.person_identifier_keys AS
 SELECT DISTINCT sa.person_id,
        k.k AS id_type,
        (sa.person_identifiers ->> k.k) AS id_value
   FROM (public.source_authorships sa
     CROSS JOIN unnest(ARRAY['orcid'::text, 'idref'::text, 'hal_person_id'::text, 'idhal'::text]) k(k))
  WHERE sa.person_id IS NOT NULL
    AND sa.person_identifiers ? k.k
    AND (sa.person_identifiers ->> k.k) !~~ '%_dubious'::text
 WITH NO DATA;

CREATE UNIQUE INDEX idx_person_identifier_keys_uq
    ON public.person_identifier_keys USING btree (person_id, id_type, id_value);
CREATE INDEX idx_person_identifier_keys_value
    ON public.person_identifier_keys USING btree (id_type, id_value);
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
