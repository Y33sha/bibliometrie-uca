"""Une adresse par forme normalisée

`addresses` devient unique par `normalized_text`, et une forme normalisée vide est refusée. L'index unique sur le texte brut disparaît : deux textes bruts distincts de même forme normalisée désignent la même adresse.

Précédée par `recompute_normalized_texts` puis `merge_address_twins`, qui fusionnent les jumelles du stock : sans eux, la création de l'index échoue.

Revision ID: 3458e6b6593b
Revises: cb20bf77cb40
Create Date: 2026-10-16 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3458e6b6593b"
down_revision: str | Sequence[str] | None = "cb20bf77cb40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX addresses_normalized_text_key
            ON structures.addresses (md5(normalized_text));
        ALTER TABLE structures.addresses
            ADD CONSTRAINT ck_addresses_normalized_text_not_empty CHECK (normalized_text <> '');
        DROP INDEX structures.addresses_raw_text_key;
    """)


def downgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX addresses_raw_text_key ON structures.addresses (md5(raw_text));
        ALTER TABLE structures.addresses DROP CONSTRAINT ck_addresses_normalized_text_not_empty;
        DROP INDEX structures.addresses_normalized_text_key;
    """)
