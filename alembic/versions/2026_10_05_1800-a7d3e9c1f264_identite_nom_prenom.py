"""Identités d'auteur : clé réduite au nom, au prénom et aux identifiants

La clé d'identité de `author_identifying_keys` devient `(last_name_normalized, first_name_normalized, person_identifiers)`. `last_name_normalized` est obligatoire. `author_name_normalized` devient une colonne calculée : prénom et nom normalisés, les parties vides omises.

À appliquer après `backfill_signature_names`, qui rattache toutes les signatures à une identité découpée.

Revision ID: a7d3e9c1f264
Revises: c4f8a1d6e293
Create Date: 2026-10-05 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7d3e9c1f264"
down_revision: str | Sequence[str] | None = "c4f8a1d6e293"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
DROP INDEX public.author_identifying_keys_key_hash_idx;
ALTER TABLE public.author_identifying_keys
    DROP CONSTRAINT author_identifying_keys_key,
    DROP COLUMN key_hash,
    DROP COLUMN author_name_normalized;

ALTER TABLE public.author_identifying_keys
    ALTER COLUMN last_name_normalized SET NOT NULL,
    ADD COLUMN author_name_normalized text
        GENERATED ALWAYS AS (
            CASE
                WHEN coalesce(first_name_normalized, '') = '' THEN last_name_normalized
                WHEN last_name_normalized = '' THEN first_name_normalized
                ELSE first_name_normalized || ' ' || last_name_normalized
            END
        ) STORED,
    ADD COLUMN key_hash text
        GENERATED ALWAYS AS (
            md5(
                coalesce((last_name_normalized)::text, E'\x01')
                || E'\x1f' || coalesce((first_name_normalized)::text, E'\x01')
                || E'\x1f' || coalesce((person_identifiers)::text, E'\x01')
            )
        ) STORED,
    ADD CONSTRAINT author_identifying_keys_key
        UNIQUE NULLS NOT DISTINCT (last_name_normalized, first_name_normalized, person_identifiers);

CREATE INDEX author_identifying_keys_key_hash_idx
    ON public.author_identifying_keys (key_hash);
"""

_DOWNGRADE = r"""
DROP INDEX public.author_identifying_keys_key_hash_idx;
ALTER TABLE public.author_identifying_keys
    DROP CONSTRAINT author_identifying_keys_key,
    DROP COLUMN key_hash,
    ADD COLUMN author_name_normalized_plain text;
UPDATE public.author_identifying_keys SET author_name_normalized_plain = author_name_normalized;
ALTER TABLE public.author_identifying_keys DROP COLUMN author_name_normalized;
ALTER TABLE public.author_identifying_keys
    RENAME COLUMN author_name_normalized_plain TO author_name_normalized;

ALTER TABLE public.author_identifying_keys
    ALTER COLUMN last_name_normalized DROP NOT NULL,
    ADD COLUMN key_hash text
        GENERATED ALWAYS AS (
            md5(
                coalesce((author_name_normalized)::text, E'\x01')
                || E'\x1f' || coalesce((last_name_normalized)::text, E'\x01')
                || E'\x1f' || coalesce((first_name_normalized)::text, E'\x01')
                || E'\x1f' || coalesce((person_identifiers)::text, E'\x01')
            )
        ) STORED,
    ADD CONSTRAINT author_identifying_keys_key
        UNIQUE NULLS NOT DISTINCT
        (author_name_normalized, last_name_normalized, first_name_normalized, person_identifiers);

CREATE INDEX author_identifying_keys_key_hash_idx
    ON public.author_identifying_keys (key_hash);
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
