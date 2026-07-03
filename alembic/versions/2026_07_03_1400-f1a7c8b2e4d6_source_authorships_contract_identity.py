"""source_authorships : identity_id NOT NULL + FK, DROP des colonnes déménagées (contract)

Phase de contraction de la scission `source_authorships` / `author_identifying_keys`.
Les écrivains posent tous `identity_id` et plus aucun lecteur ne lit
`author_name_normalized` / `person_identifiers` sur la liaison : la colonne passe
NOT NULL avec sa clé étrangère vers la table d'identités, et les deux colonnes
d'identification sont supprimées (espace récupéré au `VACUUM FULL`/repack).

Le downgrade recrée les colonnes vides : les valeurs ne sont pas restaurables
depuis l'identité par signature sans re-projeter, et l'inverse n'est de toute
façon utile qu'en secours de développement.

Revision ID: f1a7c8b2e4d6
Revises: e3b9d1c47a56
Create Date: 2026-07-03 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1a7c8b2e4d6"
down_revision: str | Sequence[str] | None = "e3b9d1c47a56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = """
ALTER TABLE public.source_authorships ALTER COLUMN identity_id SET NOT NULL;

ALTER TABLE public.source_authorships
    ADD CONSTRAINT source_authorships_identity_id_fkey
    FOREIGN KEY (identity_id) REFERENCES public.author_identifying_keys (id);

ALTER TABLE public.source_authorships DROP COLUMN author_name_normalized;
ALTER TABLE public.source_authorships DROP COLUMN person_identifiers;
"""

_DOWNGRADE = """
ALTER TABLE public.source_authorships ADD COLUMN author_name_normalized text;
ALTER TABLE public.source_authorships ADD COLUMN person_identifiers jsonb;

ALTER TABLE public.source_authorships DROP CONSTRAINT source_authorships_identity_id_fkey;
ALTER TABLE public.source_authorships ALTER COLUMN identity_id DROP NOT NULL;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
