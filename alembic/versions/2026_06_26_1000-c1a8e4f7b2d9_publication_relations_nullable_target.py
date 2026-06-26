"""publication_relations : cible par publication OU par DOI (target_doi nullable)

Une relation peut désormais cibler une œuvre **au corpus sans DOI** : son identité
est alors `target_publication_id`, pas un DOI. Jusqu'ici `target_doi` était NOT NULL
et portait la PK — adapté aux relations issues des sources (qui pointent toujours un
DOI), mais pas à celles qu'on dérive en interne (rapprochement par titre vers une
publication au corpus, qui n'a pas nécessairement de DOI).

`target_doi` devient nullable ; une PK de substitution `id` remplace l'ancienne PK
sur `target_doi`. L'unicité passe sur `(from_publication_id, relation_type,
target_publication_id, target_doi)` en `NULLS NOT DISTINCT`, qui dédoublonne aussi
bien les cibles désignées par publication que par DOI (les NULL se comparent égaux).
Un CHECK garantit qu'une cible existe (publication ou DOI).

Revision ID: c1a8e4f7b2d9
Revises: d7f2a4c9e1b6
Create Date: 2026-06-26 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1a8e4f7b2d9"
down_revision: str | Sequence[str] | None = "d7f2a4c9e1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # L'ancienne PK porte `target_doi` : la retirer avant de relâcher la colonne.
    op.execute(
        "ALTER TABLE public.publication_relations DROP CONSTRAINT publication_relations_pkey"
    )
    op.execute("ALTER TABLE public.publication_relations ALTER COLUMN target_doi DROP NOT NULL")
    op.execute(
        "ALTER TABLE public.publication_relations "
        "ADD COLUMN id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
    )
    op.execute(
        """
        ALTER TABLE public.publication_relations
            ADD CONSTRAINT publication_relations_target_present
            CHECK (target_publication_id IS NOT NULL OR target_doi IS NOT NULL)
        """
    )
    op.execute(
        """
        ALTER TABLE public.publication_relations
            ADD CONSTRAINT publication_relations_uq
            UNIQUE NULLS NOT DISTINCT
            (from_publication_id, relation_type, target_publication_id, target_doi)
        """
    )


def downgrade() -> None:
    # Les relations sans DOI cible (cibles au corpus sans DOI) ne tiennent pas dans
    # l'ancien modèle où `target_doi` portait la PK : on les retire avant de rétablir.
    op.execute("DELETE FROM public.publication_relations WHERE target_doi IS NULL")
    op.execute("ALTER TABLE public.publication_relations DROP CONSTRAINT publication_relations_uq")
    op.execute(
        "ALTER TABLE public.publication_relations "
        "DROP CONSTRAINT publication_relations_target_present"
    )
    op.execute("ALTER TABLE public.publication_relations DROP COLUMN id")
    op.execute("ALTER TABLE public.publication_relations ALTER COLUMN target_doi SET NOT NULL")
    op.execute(
        "ALTER TABLE public.publication_relations "
        "ADD PRIMARY KEY (from_publication_id, relation_type, target_doi)"
    )
