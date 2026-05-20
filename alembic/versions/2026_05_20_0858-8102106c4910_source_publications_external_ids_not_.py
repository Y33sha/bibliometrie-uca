"""source_publications.external_ids NOT NULL DEFAULT '{}' + CHECK is object

Revision ID: 8102106c4910
Revises: fc06f11bd3e0
Create Date: 2026-05-20 08:58:53.854194

Bug racine : `bindparam(type_=JSONB)` côté SA/psycopg3 convertit Python
`None` en `Jsonb(None)` → JSONB `'null'` dans la colonne (≠ SQL NULL).
Le `COALESCE(col, '{}')` des UPSERT ne catche pas JSONB null, et
`'null'::jsonb || '{}'::jsonb` produit `[null, {}]` (concat = array).
Conséquence : ~46 000 rows en violation du contrat (`dict | None`),
crash `'list' object has no attribute 'items'` en phase publications.

Cette migration cimente l'invariant "external_ids est toujours un
objet JSON" via NOT NULL + DEFAULT '{}' + CHECK jsonb_typeof = 'object'.
Le data fix one-shot (SQL via psql) a été lancé en amont pour normaliser
l'existant ; on ré-applique ici par sécurité au cas où la migration
serait jouée sur un environnement qui ne l'aurait pas reçu.

Côté Python, les 6 normalize_*.py queries substituent `None` → `{}`
avant binding pour ne jamais déclencher le CHECK.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8102106c4910"
down_revision: str | Sequence[str] | None = "fc06f11bd3e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Normalisation des valeurs aberrantes (idempotent : ne touche que ce qui n'est pas un objet).
    op.execute("""
        UPDATE source_publications
        SET external_ids = '{}'::jsonb
        WHERE external_ids IS NULL
           OR jsonb_typeof(external_ids) != 'object'
    """)

    op.alter_column(
        "source_publications",
        "external_ids",
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )

    op.create_check_constraint(
        "source_publications_external_ids_is_object",
        "source_publications",
        "jsonb_typeof(external_ids) = 'object'",
    )

    # L'index GIN existant filtrait sur `external_ids IS NOT NULL` (devenu
    # toujours vrai). On le recrée avec un filtre utile : exclure les rows
    # vides du GIN pour le garder léger.
    op.drop_index(
        op.f("idx_source_pubs_external_ids"),
        table_name="source_publications",
        postgresql_using="gin",
        postgresql_where=sa.text("external_ids IS NOT NULL"),
    )
    op.create_index(
        "idx_source_pubs_external_ids",
        "source_publications",
        ["external_ids"],
        postgresql_using="gin",
        postgresql_where=sa.text("external_ids != '{}'::jsonb"),
    )


def downgrade() -> None:
    op.drop_index(
        op.f("idx_source_pubs_external_ids"),
        table_name="source_publications",
        postgresql_using="gin",
        postgresql_where=sa.text("external_ids != '{}'::jsonb"),
    )
    op.create_index(
        "idx_source_pubs_external_ids",
        "source_publications",
        ["external_ids"],
        postgresql_using="gin",
        postgresql_where=sa.text("external_ids IS NOT NULL"),
    )

    op.drop_constraint(
        "source_publications_external_ids_is_object",
        "source_publications",
        type_="check",
    )

    op.alter_column(
        "source_publications",
        "external_ids",
        nullable=True,
        server_default=None,
    )
