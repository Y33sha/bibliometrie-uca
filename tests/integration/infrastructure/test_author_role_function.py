"""La fonction SQL `is_author_role` reprend les rôles d'auteur du domaine (`AUTHOR_ROLES`)."""

from sqlalchemy import text

from domain.contributions.contribution_roles import AUTHOR_ROLES, ContributionRole


def test_is_author_role_matches_author_roles(sa_sync_conn):
    sql_author_roles = {
        role
        for role in ContributionRole
        if sa_sync_conn.execute(
            text("SELECT is_author_role(ARRAY[:role])"), {"role": role.value}
        ).scalar_one()
    }

    assert sql_author_roles == AUTHOR_ROLES
