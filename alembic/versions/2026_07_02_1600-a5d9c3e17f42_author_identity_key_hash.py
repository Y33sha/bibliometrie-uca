"""author_identifying_keys : colonne générée key_hash + index (lookup NULL-safe indexé)

La clé d'identité `(author_name_normalized, person_identifiers)` est composite et nullable : `person_identifiers` est `NULL` sur la majorité des signatures. Résoudre l'identité d'une signature par cette clé ne peut se faire ni par `=` (les valeurs `NULL` ne matchent pas) ni par `IS NOT DISTINCT FROM` (non indexable). La colonne générée `key_hash` matérialise un md5 des deux champs, `NULL` remplacé par des sentinelles impossibles dans les vraies valeurs (`E'\x01'` : caractère de contrôle absent des noms normalisés et des `jsonb::text` ; `E'\x1f'` : séparateur de champs). Un lookup `WHERE key_hash = md5(…)` est alors indexé et NULL-safe, et respecte le `NULLS NOT DISTINCT` de l'unique (deux `(NULL, NULL)` produisent le même hash).

L'unique `(author_name_normalized, person_identifiers) NULLS NOT DISTINCT` reste la garantie d'identité ; `key_hash` n'est qu'un chemin de lookup (index non unique : une collision md5, astronomiquement improbable, se départage par la clé exacte côté appelant).

Revision ID: a5d9c3e17f42
Revises: b8e4c1f9a207
Create Date: 2026-07-02 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a5d9c3e17f42"
down_revision: str | Sequence[str] | None = "b8e4c1f9a207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
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
"""

_DOWNGRADE = """
DROP INDEX IF EXISTS public.author_identifying_keys_key_hash_idx;
ALTER TABLE public.author_identifying_keys DROP COLUMN IF EXISTS key_hash;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
