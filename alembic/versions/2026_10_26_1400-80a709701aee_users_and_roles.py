"""Utilisateurs autorisés et leurs rôles

Revision ID: 80a709701aee
Revises: f3c9a5b7d214
Create Date: 2026-10-26 14:00:00.000000

`ops.users` liste les utilisateurs autorisés à ouvrir une session, par leur identifiant de connexion. `ops.roles` énumère les rôles que le code connaît (`domain.users.Role`), `ops.user_roles` les attribue.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "80a709701aee"
down_revision: str | Sequence[str] | None = "f3c9a5b7d214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ops.users (
            id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            login text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT users_login_key UNIQUE (login)
        )
    """)
    op.execute("COMMENT ON TABLE ops.users IS 'Utilisateurs autorisés à ouvrir une session.'")
    op.execute(
        "COMMENT ON COLUMN ops.users.login IS "
        "'Identifiant de connexion : identifiant CAS, ou ADMIN_USER pour la connexion par mot de passe.'"
    )
    op.execute("""
        CREATE TABLE ops.roles (
            code text PRIMARY KEY,
            label text NOT NULL
        )
    """)
    op.execute("COMMENT ON TABLE ops.roles IS 'Rôles que le code connaît (domain.users.Role).'")
    op.execute("""
        CREATE TABLE ops.user_roles (
            user_id integer NOT NULL REFERENCES ops.users (id) ON DELETE CASCADE,
            role_code text NOT NULL REFERENCES ops.roles (code),
            PRIMARY KEY (user_id, role_code)
        )
    """)
    op.execute("COMMENT ON TABLE ops.user_roles IS 'Rôles attribués à chaque utilisateur.'")
    op.execute("INSERT INTO ops.roles (code, label) VALUES ('admin', 'Administration')")


def downgrade() -> None:
    op.execute("DROP TABLE ops.user_roles")
    op.execute("DROP TABLE ops.roles")
    op.execute("DROP TABLE ops.users")
