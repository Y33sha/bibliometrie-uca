"""drop pipeline_run_snapshots

Retire la table de l'ancien système d'observabilité « par run complet »,
supplanté par `pipeline_phase_executions` (une ligne par exécution de phase).
La séquence `pipeline_run_id_seq` n'est pas touchée : elle reste utilisée par
la table des exécutions de phase.

Revision ID: 4477146f78cf
Revises: 0001
Create Date: 2026-06-30 10:18:49.402421
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4477146f78cf"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # CASCADE emporte l'index et la séquence détenue par la table.
    op.execute("DROP TABLE IF EXISTS public.pipeline_run_snapshots CASCADE")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.pipeline_run_snapshots (
            id integer NOT NULL,
            ran_at timestamp with time zone DEFAULT now() NOT NULL,
            mode text NOT NULL,
            payload jsonb NOT NULL
        );
        CREATE SEQUENCE public.pipeline_run_snapshots_id_seq AS integer
            START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
        ALTER SEQUENCE public.pipeline_run_snapshots_id_seq
            OWNED BY public.pipeline_run_snapshots.id;
        ALTER TABLE ONLY public.pipeline_run_snapshots
            ALTER COLUMN id SET DEFAULT nextval('public.pipeline_run_snapshots_id_seq'::regclass);
        ALTER TABLE ONLY public.pipeline_run_snapshots
            ADD CONSTRAINT pipeline_check_snapshots_pkey PRIMARY KEY (id);
        CREATE INDEX idx_pipeline_run_snapshots_mode_ran_at
            ON public.pipeline_run_snapshots USING btree (mode, ran_at DESC);
        """
    )
