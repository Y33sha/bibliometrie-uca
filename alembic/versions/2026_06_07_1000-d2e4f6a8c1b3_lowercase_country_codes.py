"""backfill : codes pays en minuscules (canonique) dans les arrays

Le code pays canonique est minuscule (`countries.code`), mais `normalize_openalex`
écrivait les codes ISO OpenAlex en majuscules dans `addresses.suggested_countries`
(corrigé en `.lower()`), d'où des doublons de casse (`FR` et `fr`) qui polluaient
le dropdown admin/countries. Des codes majuscules ont aussi fuité dans
`addresses.countries` (suggestions acceptées) et `publications.countries` (dérivé).

Backfill : normalise chaque array en minuscules + dédup. Idempotent (ne touche que
les lignes qui changent). Irréversible (la casse d'origine est perdue) → downgrade
no-op.

Revision ID: d2e4f6a8c1b3
Revises: a1b2c3d4e5f6
Create Date: 2026-06-07 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2e4f6a8c1b3"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _lowercase_array(table: str, column: str) -> str:
    return f"""
        UPDATE {table} t
        SET {column} = norm.arr
        FROM (
            SELECT t2.id, array_agg(DISTINCT lower(x) ORDER BY lower(x)) AS arr
            FROM {table} t2, unnest(t2.{column}) AS x
            WHERE t2.{column} IS NOT NULL
            GROUP BY t2.id
        ) norm
        WHERE t.id = norm.id
          AND t.{column}::text[] IS DISTINCT FROM norm.arr
    """


def upgrade() -> None:
    op.execute(_lowercase_array("addresses", "suggested_countries"))
    op.execute(_lowercase_array("addresses", "countries"))
    op.execute(_lowercase_array("publications", "countries"))


def downgrade() -> None:
    # Irréversible : la casse d'origine n'est pas conservée.
    pass
