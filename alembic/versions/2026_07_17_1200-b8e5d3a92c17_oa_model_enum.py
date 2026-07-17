"""journals.oa_model : contrainte CHECK convertie en enum

Le vocabulaire de `oa_model` est déclaré par le domaine (`domain.journals.journal.OaModel`) et
tenu en base par une contrainte `CHECK`. Ses voisins de même nature — `journal_type`,
`publisher_type`, `source_type` — sont des enums ; `oa_model` s'aligne. L'enum se prête à
l'introspection (`enum_range`), ce qui donne à l'accord domaine/base le même test que celui de
`journal_type`, et le contrat de lecture de l'API annonce les trois valeurs plutôt qu'un texte.

La contrainte tombe avant la conversion : son expression compare `oa_model` à du texte, ce qu'un
`ALTER COLUMN TYPE` réévalue et qu'aucun opérateur ne sait faire une fois la colonne en enum.
Elle est sans objet ensuite, l'enum portant la même règle.

Revision ID: b8e5d3a92c17
Revises: a3d7f1c9b524
Create Date: 2026-07-17 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8e5d3a92c17"
down_revision: str | Sequence[str] | None = "a3d7f1c9b524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.journals DROP CONSTRAINT journals_oa_model_check;")
    op.execute("CREATE TYPE oa_model AS ENUM ('subscription', 'full_oa', 'repository');")
    op.execute(
        "ALTER TABLE public.journals ALTER COLUMN oa_model TYPE oa_model USING oa_model::oa_model;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.journals ALTER COLUMN oa_model TYPE text USING oa_model::text;")
    op.execute("DROP TYPE oa_model;")
    op.execute(
        "ALTER TABLE public.journals ADD CONSTRAINT journals_oa_model_check "
        "CHECK (oa_model IS NULL OR oa_model IN ('subscription', 'full_oa', 'repository'));"
    )
