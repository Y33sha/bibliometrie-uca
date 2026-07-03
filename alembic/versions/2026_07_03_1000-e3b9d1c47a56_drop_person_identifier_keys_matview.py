"""Supprime la matview person_identifier_keys, index couvrant idx_sa_person

La file « conflits d'identifiant » du hub admin lit désormais les triplets
`(person_id, id_type, id_value)` par un CTE inline (seul consommateur), sans
objet vue intermédiaire. L'index partiel `idx_sa_person` est étendu à
`(person_id, identity_id)` : `person_id` en tête sert toujours les recherches
par personne, et `identity_id` en colonne incluse permet à ce CTE un index-only
scan de `source_authorships` (0 heap fetch) avant la jointure sur
`author_identifying_keys`. La matview et son `REFRESH` du pipeline disparaissent.

Revision ID: e3b9d1c47a56
Revises: d7a2f6b3e918
Create Date: 2026-07-03 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3b9d1c47a56"
down_revision: str | Sequence[str] | None = "d7a2f6b3e918"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
DROP MATERIALIZED VIEW public.person_identifier_keys;

DROP INDEX public.idx_sa_person;
CREATE INDEX idx_sa_person ON public.source_authorships
    USING btree (person_id, identity_id) WHERE (person_id IS NOT NULL);
"""

_DOWNGRADE = """
DROP INDEX public.idx_sa_person;
CREATE INDEX idx_sa_person ON public.source_authorships
    USING btree (person_id) WHERE (person_id IS NOT NULL);

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


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
