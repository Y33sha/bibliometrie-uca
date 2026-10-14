"""Droits des rôles réalignés sur `grants.sql`, directement et après une migration jouée."""

import psycopg
from sqlalchemy import text

from alembic import command
from infrastructure.db.grants import apply_grants
from tests.integration.conftest import DB_NAME, _admin_connect_args, _alembic_config

_CAN_DELETE_REJECTIONS = (
    "SELECT has_table_privilege('bibliometrie_app', 'persons.rejected_authorships', 'DELETE')"
)


def test_apply_grants_restores_a_revoked_right(sa_sync_conn_owner):
    conn = sa_sync_conn_owner
    conn.execute(text("REVOKE DELETE ON persons.rejected_authorships FROM bibliometrie_app"))
    assert conn.execute(text(_CAN_DELETE_REJECTIONS)).scalar() is False

    assert apply_grants(conn)

    assert conn.execute(text(_CAN_DELETE_REJECTIONS)).scalar() is True


def test_migration_realigns_grants():
    """Une migration jouée réapplique les droits : un droit retiré hors de `grants.sql` revient."""
    args = _admin_connect_args()
    args["dbname"] = DB_NAME
    with psycopg.connect(**args, autocommit=True) as conn:
        conn.execute("REVOKE DELETE ON persons.rejected_authorships FROM bibliometrie_app")

    command.downgrade(_alembic_config(), "-1")
    command.upgrade(_alembic_config(), "head")

    with psycopg.connect(**args) as conn:
        assert conn.execute(_CAN_DELETE_REJECTIONS).fetchone() == (True,)
