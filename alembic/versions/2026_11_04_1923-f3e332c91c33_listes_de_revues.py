"""Listes de revues

Revision ID: f3e332c91c33
Revises: e5538373a92d
Create Date: 2026-11-04 19:23:02.368710

`serial_lists` réunit les listes de revues reprises d'OpenAlex et les classements qui regroupent des niveaux. `serial_list_entries` donne les listes de chaque publication en série. La migration insère les listes retenues ; l'import renseigne leur organisme, leur URL et leur édition.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3e332c91c33"
down_revision: str | Sequence[str] | None = "e5538373a92d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE publishing.serial_lists (
            code text PRIMARY KEY,
            ranking_code text REFERENCES publishing.serial_lists(code),
            label text NOT NULL,
            display_order integer NOT NULL,
            maintainer text,
            url text,
            edition date
        );
        COMMENT ON TABLE publishing.serial_lists IS
            'Listes de revues. Un classement à niveaux est une ligne sans appartenances, parente de ses niveaux.';
        COMMENT ON COLUMN publishing.serial_lists.code IS
            'Code de la liste dans OpenAlex (`listed_in`), ou code du classement.';
        COMMENT ON COLUMN publishing.serial_lists.ranking_code IS
            'Classement du niveau.';
        COMMENT ON COLUMN publishing.serial_lists.maintainer IS
            'Organisme qui publie la liste, d''après OpenAlex.';
        COMMENT ON COLUMN publishing.serial_lists.edition IS
            'Date de l''édition de la liste chargée par OpenAlex.';

        CREATE TABLE publishing.serial_list_entries (
            serial_id integer NOT NULL REFERENCES publishing.serials(id) ON DELETE CASCADE,
            list_code text NOT NULL REFERENCES publishing.serial_lists(code) ON DELETE CASCADE,
            PRIMARY KEY (serial_id, list_code)
        );
        COMMENT ON TABLE publishing.serial_list_entries IS
            'Appartenance d''une publication en série à une liste, d''après OpenAlex.';

        INSERT INTO publishing.serial_lists (code, ranking_code, label, display_order) VALUES
            ('doyens', NULL, 'Conférence des doyens de médecine', 1),
            ('doaj', NULL, 'DOAJ', 2),
            ('medline', NULL, 'MEDLINE', 3),
            ('cwts-core', NULL, 'Leiden Ranking (CWTS)', 4),
            ('ddh', NULL, 'Diamond Discovery Hub', 5),
            ('erih-plus', NULL, 'ERIH PLUS', 6),
            ('norway', NULL, 'Registre norvégien', 7),
            ('norway-1', 'norway', 'niveau 1', 8),
            ('norway-2', 'norway', 'niveau 2', 9),
            ('fnege', NULL, 'FNEGE', 10),
            ('fnege-1-star', 'fnege', 'rang 1*', 11),
            ('fnege-1', 'fnege', 'rang 1', 12),
            ('fnege-2', 'fnege', 'rang 2', 13),
            ('fnege-3', 'fnege', 'rang 3', 14),
            ('fnege-4', 'fnege', 'rang 4', 15);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE publishing.serial_list_entries;
        DROP TABLE publishing.serial_lists;
    """)
