"""confirmed_authorships : épinglage admin d'une signature à une personne (must-link)

Pendant positif de `rejected_authorships`, au grain **signature** : une résolution admin
d'orpheline (rattachement d'une `source_authorships` à une personne) s'y inscrit et devient
une entrée fixe du canal nominal ordre-indépendant — le recompute la lit comme épinglage
dur et ne la re-dérive jamais. Clé primaire sur `source_authorship_id` : une signature est
épinglée au plus une fois, vers une seule personne (épingler deux fois vers deux personnes
est une contradiction que la base refuse). Les FK `ON DELETE CASCADE` retirent l'épinglage
quand la signature ou la personne disparaît.

Revision ID: a1c4e7b09f52
Revises: e2b5a8d3f0c9
Create Date: 2026-07-07 12:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1c4e7b09f52"
down_revision: str | Sequence[str] | None = "e2b5a8d3f0c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
CREATE TABLE public.confirmed_authorships (
    source_authorship_id integer NOT NULL,
    person_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);

ALTER TABLE ONLY public.confirmed_authorships
    ADD CONSTRAINT confirmed_authorships_pkey PRIMARY KEY (source_authorship_id);
ALTER TABLE ONLY public.confirmed_authorships
    ADD CONSTRAINT confirmed_authorships_source_authorship_id_fkey
    FOREIGN KEY (source_authorship_id) REFERENCES public.source_authorships(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.confirmed_authorships
    ADD CONSTRAINT confirmed_authorships_person_id_fkey
    FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE CASCADE;

CREATE INDEX idx_confirmed_authorships_person ON public.confirmed_authorships USING btree (person_id);
"""

_DOWNGRADE = """
DROP TABLE IF EXISTS public.confirmed_authorships CASCADE;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
