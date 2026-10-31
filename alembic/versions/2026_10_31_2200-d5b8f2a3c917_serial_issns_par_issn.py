"""`serial_issns` à une ligne par ISSN, liens entre ISSN, décisions de rattachement par titre, formes de nom des revues supprimées

Revision ID: d5b8f2a3c917
Revises: c4a7e19d2b56
Create Date: 2026-10-31 22:00:00.000000

`serial_issns` contient une ligne par ISSN valide, avec son ISSN-L (`issnl`). Sa colonne `serial_id` désigne la revue de cet ISSN-L. Les valeurs mal formées sont supprimées. Un ISSN présent dans plusieurs lignes en garde une seule. Un ISSN d'un titre précédent, d'un titre suivant ou d'un supplément quitte sa revue et repasse à la vérification Sudoc, qui écrit ses liens dans `issn_links`. L'énumération `issn_status` garde `active`, `cancelled` et `unverified`.

`serial_title_decisions` garde les fusions décidées par l'administration d'une revue sans ISSN dans une autre revue. `issns` quitte les champs saisis à la main des revues. `serial_name_forms` est supprimée. `sudoc_max_per_run` compte des ISSN.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d5b8f2a3c917"
down_revision: str | Sequence[str] | None = "c4a7e19d2b56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _recreate_status(values: str, old_name: str) -> str:
    return f"""
        ALTER TYPE public.issn_status RENAME TO {old_name};
        CREATE TYPE public.issn_status AS ENUM ({values});
        ALTER TABLE publishing.serial_issns ALTER COLUMN status DROP DEFAULT;
        ALTER TABLE publishing.serial_issns
            ALTER COLUMN status TYPE public.issn_status USING status::text::public.issn_status;
        ALTER TABLE publishing.serial_issns ALTER COLUMN status SET DEFAULT 'active';
        DROP TYPE public.{old_name};
    """


def upgrade() -> None:
    op.execute("""
        DELETE FROM publishing.serial_issns WHERE status = 'malformed';

        ALTER TABLE publishing.serial_issns ADD COLUMN issnl text;

        UPDATE publishing.serial_issns i
        SET issnl = (SELECT l.issn FROM publishing.serial_issns l
                     WHERE l.serial_id = i.serial_id AND l.linking LIMIT 1)
        WHERE i.serial_id IS NOT NULL AND i.status IN ('active', 'cancelled', 'unverified');

        UPDATE publishing.serial_issns
        SET serial_id = NULL, status = 'active', sudoc_checked_at = NULL
        WHERE status IN ('related_title', 'supplement');

        -- Un ISSN présent dans plusieurs lignes garde la ligne rattachée à une revue, puis celle de l'ISSN-L, puis la ligne vérifiée, puis la plus ancienne.
        DELETE FROM publishing.serial_issns i
        USING (
            SELECT id, row_number() OVER (
                PARTITION BY issn
                ORDER BY serial_id IS NOT NULL DESC, linking DESC,
                         sudoc_checked_at IS NOT NULL DESC, id
            ) AS rank
            FROM publishing.serial_issns
        ) ranked
        WHERE i.id = ranked.id AND ranked.rank > 1;

        DROP INDEX publishing.uq_serial_issns_linking;
        ALTER TABLE publishing.serial_issns DROP COLUMN linking;
        ALTER TABLE publishing.serial_issns DROP CONSTRAINT uq_serial_issns_issn_serial;
        ALTER TABLE publishing.serial_issns ADD CONSTRAINT uq_serial_issns_issn UNIQUE (issn);
    """)
    op.execute(_recreate_status("'active', 'cancelled', 'unverified'", "issn_status_by_serial"))
    op.execute("""
        COMMENT ON TABLE publishing.serial_issns IS
        'ISSN valides, une ligne par ISSN, et revue de leur ISSN-L.';
        COMMENT ON COLUMN publishing.serial_issns.issn IS 'ISSN, forme normalisée.';
        COMMENT ON COLUMN publishing.serial_issns.issnl IS
        'ISSN-L de l''ISSN d''après sa notice Sudoc. NULL : inconnu.';
        COMMENT ON COLUMN publishing.serial_issns.serial_id IS
        'Revue de l''ISSN-L de l''ISSN, calculée par la phase publishing.';
        COMMENT ON COLUMN publishing.serial_issns.status IS
        'active ; cancelled (ISSN annulé) ; unverified (sans notice Sudoc).';

        CREATE TYPE public.issn_link_type AS ENUM ('continued_by', 'supplement');

        CREATE TABLE publishing.issn_links (
            issn text NOT NULL,
            linked_issn text NOT NULL,
            link_type public.issn_link_type NOT NULL,
            PRIMARY KEY (issn, linked_issn, link_type)
        );
        CREATE INDEX idx_issn_links_linked ON publishing.issn_links (linked_issn);
        COMMENT ON TABLE publishing.issn_links IS
        'Liens entre ISSN lus dans le Sudoc, une ligne par lien : continued_by, titre précédent vers titre suivant ; supplement, revue principale vers supplément.';

        CREATE TABLE publishing.serial_title_decisions (
            id serial PRIMARY KEY,
            title_normalized text NOT NULL,
            publisher_id integer REFERENCES publishing.publishers(id) ON DELETE CASCADE,
            serial_id integer NOT NULL REFERENCES publishing.serials(id) ON DELETE CASCADE,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            CONSTRAINT uq_serial_title_decisions UNIQUE NULLS NOT DISTINCT
                (title_normalized, publisher_id)
        );
        COMMENT ON TABLE publishing.serial_title_decisions IS
        'Fusions décidées par l''administration : une série sans ISSN, de ce titre normalisé et de cet éditeur, est rattachée à la revue.';

        UPDATE publishing.serials SET manual_fields = array_remove(manual_fields, 'issns')
        WHERE 'issns' = ANY(manual_fields);

        DROP TABLE publishing.serial_name_forms;

        UPDATE ops.config
        SET description = 'Nombre maximum d''ISSN vérifiés dans le Sudoc par run. 0 = illimité.'
        WHERE key = 'sudoc_max_per_run';
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE ops.config
        SET description = 'Nombre maximum de revues vérifiées dans le Sudoc par run. 0 = illimité.'
        WHERE key = 'sudoc_max_per_run';

        CREATE TABLE publishing.serial_name_forms (
            id serial PRIMARY KEY,
            serial_id integer NOT NULL REFERENCES publishing.serials(id) ON DELETE CASCADE,
            form_normalized text NOT NULL,
            created_at timestamp with time zone DEFAULT now(),
            publisher_id integer REFERENCES publishing.publishers(id),
            CONSTRAINT uq_serial_name_forms_form_publisher
                UNIQUE NULLS NOT DISTINCT (form_normalized, publisher_id)
        );
        CREATE INDEX idx_serial_name_forms_serial ON publishing.serial_name_forms (serial_id);

        DROP TABLE publishing.serial_title_decisions;
        DROP TABLE publishing.issn_links;
        DROP TYPE public.issn_link_type;
    """)
    op.execute(
        _recreate_status(
            "'active', 'malformed', 'cancelled', 'related_title', 'supplement', 'unverified'",
            "issn_status_by_issn",
        )
    )
    op.execute("""
        ALTER TABLE publishing.serial_issns DROP CONSTRAINT uq_serial_issns_issn;
        ALTER TABLE publishing.serial_issns ADD CONSTRAINT uq_serial_issns_issn_serial
            UNIQUE NULLS NOT DISTINCT (issn, serial_id);
        ALTER TABLE publishing.serial_issns
            ADD COLUMN linking boolean NOT NULL DEFAULT false;
        UPDATE publishing.serial_issns SET linking = true
        WHERE serial_id IS NOT NULL AND issn = issnl;
        CREATE UNIQUE INDEX uq_serial_issns_linking
            ON publishing.serial_issns (serial_id) WHERE linking;
        ALTER TABLE publishing.serial_issns DROP COLUMN issnl;
    """)
