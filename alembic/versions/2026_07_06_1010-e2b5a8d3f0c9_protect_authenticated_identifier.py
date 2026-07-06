"""Trigger protégeant le statut 'authenticated' des identifiants

Invariant porté au niveau table (défense en profondeur, quel que soit le chemin
d'écriture : pipeline, admin, script, SQL manuel) :

- 'authenticated' ne peut être posé que par l'import dédié des ORCID authentifiés,
  qui signale son contexte par le paramètre de session `app.orcid_authenticated_import`.
- un identifiant 'authenticated' ne peut plus changer de statut : aucune dégradation,
  même par l'interface admin. Le déplacement vers une autre personne (fusion) reste
  permis tant que le statut ne bouge pas.

Revision ID: e2b5a8d3f0c9
Revises: d1a4f7c2e9b8
Create Date: 2026-07-06 10:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2b5a8d3f0c9"
down_revision: str | Sequence[str] | None = "d1a4f7c2e9b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION protect_authenticated_identifier()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.status = 'authenticated'
               AND current_setting('app.orcid_authenticated_import', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION
                    'le statut authenticated ne peut etre pose que par l''import des ORCID authentifies';
            END IF;
            IF TG_OP = 'UPDATE'
               AND OLD.status = 'authenticated'
               AND NEW.status <> 'authenticated' THEN
                RAISE EXCEPTION
                    'le statut authenticated est immuable : degradation interdite (id=%)', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_protect_authenticated_identifier
            BEFORE INSERT OR UPDATE ON person_identifiers
            FOR EACH ROW EXECUTE FUNCTION protect_authenticated_identifier();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_protect_authenticated_identifier ON person_identifiers")
    op.execute("DROP FUNCTION IF EXISTS protect_authenticated_identifier()")
