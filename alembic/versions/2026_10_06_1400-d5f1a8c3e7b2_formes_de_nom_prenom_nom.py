"""Formes de nom des personnes dans l'ordre « prénom nom »

Les formes à verdict découpées en nom et prénom sont réécrites au format de `author_identifying_keys.author_name_normalized`. Les formes réécrites identiques pour une même personne fusionnent leurs sources ; un verdict `rejected` l'emporte. Les formes en attente sont supprimées : la phase `persons` les régénère. Les colonnes de découpage disparaissent. Un index sur `author_identifying_keys.author_name_normalized` sert les jointures avec `person_name_forms.name_form`.

Revision ID: d5f1a8c3e7b2
Revises: b2e7c4a9f513
Create Date: 2026-10-06 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d5f1a8c3e7b2"
down_revision: str | Sequence[str] | None = "b2e7c4a9f513"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM public.person_name_forms WHERE status = 'pending'")
    op.execute("""
        CREATE TEMP TABLE _rewritten ON COMMIT DROP AS
        SELECT CASE WHEN coalesce(f.first_name_normalized, '') = '' THEN f.last_name_normalized
                    ELSE f.first_name_normalized || ' ' || f.last_name_normalized END AS name_form,
               f.person_id,
               CASE WHEN bool_or(f.status = 'rejected') THEN 'rejected' ELSE 'confirmed' END
                   AS status,
               coalesce(array_agg(DISTINCT s ORDER BY s) FILTER (WHERE s IS NOT NULL), '{}')
                   AS sources,
               min(f.created_at) AS created_at
        FROM public.person_name_forms f
        LEFT JOIN LATERAL unnest(f.sources) AS s ON TRUE
        WHERE f.last_name_normalized IS NOT NULL
        GROUP BY 1, 2
    """)
    op.execute("DELETE FROM public.person_name_forms WHERE last_name_normalized IS NOT NULL")
    op.execute("""
        INSERT INTO public.person_name_forms (name_form, person_id, sources, status, created_at)
        SELECT name_form, person_id, sources, status::identifier_status, created_at
        FROM _rewritten
        ON CONFLICT (name_form, person_id) DO UPDATE SET
            sources = (
                SELECT coalesce(array_agg(DISTINCT s ORDER BY s), '{}')
                FROM unnest(person_name_forms.sources || EXCLUDED.sources) AS s
            )
    """)
    op.execute("""
        ALTER TABLE public.person_name_forms
            DROP CONSTRAINT person_name_forms_split,
            DROP COLUMN last_name_normalized,
            DROP COLUMN first_name_normalized
    """)
    op.execute(
        "CREATE INDEX author_identifying_keys_author_name_normalized_idx"
        " ON public.author_identifying_keys (author_name_normalized)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX public.author_identifying_keys_author_name_normalized_idx")
    op.execute("""
        ALTER TABLE public.person_name_forms
            ADD COLUMN last_name_normalized text,
            ADD COLUMN first_name_normalized text,
            ADD CONSTRAINT person_name_forms_split CHECK (
                first_name_normalized IS NULL OR last_name_normalized IS NOT NULL
            )
    """)
