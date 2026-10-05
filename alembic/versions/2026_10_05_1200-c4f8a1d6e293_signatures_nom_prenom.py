"""Signatures : nom et prénom tels que la source les donne, et dans la clé d'identité

`source_authorships` gagne `raw_last_name` et `raw_first_name`. Une signature porte soit le nom et le prénom séparés par la source, soit la chaîne brute `raw_author_name` (contrainte `source_authorships_name_form`).

`author_identifying_keys` gagne `last_name_normalized` et `first_name_normalized`, ajoutés à la clé d'identité et au `key_hash`. Les identités existantes gardent ces colonnes à NULL jusqu'au rattachement de leurs signatures à une identité découpée.

Revision ID: c4f8a1d6e293
Revises: e7c4a2f9b158
Create Date: 2026-10-05 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4f8a1d6e293"
down_revision: str | Sequence[str] | None = "e7c4a2f9b158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
ALTER TABLE public.source_authorships
    ADD COLUMN raw_last_name text,
    ADD COLUMN raw_first_name text,
    ADD CONSTRAINT source_authorships_name_form CHECK (
        num_nonnulls(raw_author_name, raw_last_name) = 1
        AND (raw_first_name IS NULL OR raw_last_name IS NOT NULL)
    );

ALTER TABLE public.author_identifying_keys
    ADD COLUMN last_name_normalized text,
    ADD COLUMN first_name_normalized text,
    DROP CONSTRAINT author_identifying_keys_key,
    ADD CONSTRAINT author_identifying_keys_key
        UNIQUE NULLS NOT DISTINCT
        (author_name_normalized, last_name_normalized, first_name_normalized, person_identifiers);

DROP INDEX public.author_identifying_keys_key_hash_idx;
ALTER TABLE public.author_identifying_keys DROP COLUMN key_hash;
ALTER TABLE public.author_identifying_keys
    ADD COLUMN key_hash text
    GENERATED ALWAYS AS (
        md5(
            coalesce((author_name_normalized)::text, E'\x01')
            || E'\x1f' || coalesce((last_name_normalized)::text, E'\x01')
            || E'\x1f' || coalesce((first_name_normalized)::text, E'\x01')
            || E'\x1f' || coalesce((person_identifiers)::text, E'\x01')
        )
    ) STORED;
CREATE INDEX author_identifying_keys_key_hash_idx
    ON public.author_identifying_keys (key_hash);
"""

_DOWNGRADE = r"""
DROP INDEX public.author_identifying_keys_key_hash_idx;
ALTER TABLE public.author_identifying_keys DROP COLUMN key_hash;
ALTER TABLE public.author_identifying_keys
    DROP CONSTRAINT author_identifying_keys_key,
    DROP COLUMN last_name_normalized,
    DROP COLUMN first_name_normalized,
    ADD CONSTRAINT author_identifying_keys_key
        UNIQUE NULLS NOT DISTINCT (author_name_normalized, person_identifiers);
ALTER TABLE public.author_identifying_keys
    ADD COLUMN key_hash text
    GENERATED ALWAYS AS (
        md5(
            coalesce(author_name_normalized, E'\x01')
            || E'\x1f'
            || coalesce(person_identifiers::text, E'\x01')
        )
    ) STORED;
CREATE INDEX author_identifying_keys_key_hash_idx
    ON public.author_identifying_keys (key_hash);

ALTER TABLE public.source_authorships
    DROP CONSTRAINT source_authorships_name_form,
    DROP COLUMN raw_last_name,
    DROP COLUMN raw_first_name;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
