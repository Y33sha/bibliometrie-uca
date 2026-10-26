"""Utilisateurs et rôles : création, lecture, retrait."""

import pytest
from psycopg.errors import InsufficientPrivilege
from sqlalchemy.exc import ProgrammingError

from domain.users import Role
from infrastructure.repositories.user_repository import PgUserRepository


def test_un_login_absent_n_a_pas_de_roles(sa_sync_conn_owner):
    assert PgUserRepository(sa_sync_conn_owner).roles_of("inconnu") is None


def test_un_utilisateur_sans_role_a_un_ensemble_vide(sa_sync_conn_owner):
    users = PgUserRepository(sa_sync_conn_owner)
    users.ensure_user("dupont", [])
    assert users.roles_of("dupont") == frozenset()


def test_ensure_user_ajoute_les_roles_sans_retirer_les_autres(sa_sync_conn_owner):
    users = PgUserRepository(sa_sync_conn_owner)
    users.ensure_user("dupont", [Role.ADMIN])
    users.ensure_user("dupont", [])
    assert users.roles_of("dupont") == {Role.ADMIN}


def test_revoke_retire_le_role(sa_sync_conn_owner):
    users = PgUserRepository(sa_sync_conn_owner)
    users.ensure_user("dupont", [Role.ADMIN])
    users.revoke("dupont", [Role.ADMIN])
    assert users.roles_of("dupont") == frozenset()


def test_remove_user_supprime_l_utilisateur_et_ses_roles(sa_sync_conn_owner):
    users = PgUserRepository(sa_sync_conn_owner)
    users.ensure_user("dupont", [Role.ADMIN])
    assert users.remove_user("dupont") is True
    assert users.roles_of("dupont") is None
    assert users.remove_user("dupont") is False


def test_list_users_trie_par_login(sa_sync_conn_owner):
    users = PgUserRepository(sa_sync_conn_owner)
    users.ensure_user("martin", [])
    users.ensure_user("dupont", [Role.ADMIN])
    assert [login for login, _ in users.list_users()] == ["dupont", "martin"]


def test_l_api_cree_un_utilisateur_admin(sa_sync_conn_app):
    """Au démarrage, l'API crée `ADMIN_USER` sous son propre rôle de connexion."""
    users = PgUserRepository(sa_sync_conn_app)
    users.ensure_user("dupont", [Role.ADMIN])
    assert users.roles_of("dupont") == {Role.ADMIN}


def test_le_pipeline_n_ecrit_pas_les_utilisateurs(sa_sync_conn):
    with pytest.raises(ProgrammingError) as refus:
        PgUserRepository(sa_sync_conn).ensure_user("dupont", [Role.ADMIN])
    assert isinstance(refus.value.orig, InsufficientPrivilege)
