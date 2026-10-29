# STATUS: maintenance
"""Gère les utilisateurs autorisés à ouvrir une session et leurs rôles.

Le script se connecte sous le propriétaire du schéma (`DB_OWNER_USER`) : le rôle du pipeline est sans droit d'écriture sur `ops.users` et `ops.user_roles`.

Usage :
    python -m interfaces.cli.maintenance.manage_users list
    python -m interfaces.cli.maintenance.manage_users add LOGIN [--role admin ...]
    python -m interfaces.cli.maintenance.manage_users revoke LOGIN --role admin [--role ...]
    python -m interfaces.cli.maintenance.manage_users remove LOGIN
"""

import argparse
import os

from domain.users import Role
from infrastructure.db.engine import build_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories.user_repository import PgUserRepository

log = setup_logger("manage_users", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Liste les utilisateurs et leurs rôles.")
    add = commands.add_parser(
        "add", help="Crée l'utilisateur s'il manque et lui attribue des rôles."
    )
    revoke = commands.add_parser("revoke", help="Retire des rôles à un utilisateur.")
    remove = commands.add_parser("remove", help="Supprime un utilisateur et ses rôles.")
    for command in (add, revoke, remove):
        command.add_argument("login")
    for command, required in ((add, False), (revoke, True)):
        command.add_argument(
            "--role",
            action="append",
            choices=[role.value for role in Role],
            default=[],
            required=required,
            help="Rôle à attribuer ou à retirer ; option répétable.",
        )
    args = parser.parse_args()

    engine = build_sync_engine("owner")
    with engine.begin() as conn:
        users = PgUserRepository(conn)
        if args.command == "list":
            for login, roles in users.list_users():
                log.info("%s : %s", login, ", ".join(sorted(roles)) or "aucun rôle")
        elif args.command == "add":
            users.ensure_user(args.login, args.role)
            log.info("%s : %s", args.login, ", ".join(sorted(users.roles_of(args.login) or [])))
        elif args.command == "revoke":
            if users.roles_of(args.login) is None:
                log.error("Utilisateur inconnu : %s", args.login)
                return 1
            users.revoke(args.login, args.role)
            log.info("%s : %s", args.login, ", ".join(sorted(users.roles_of(args.login) or [])))
        elif not users.remove_user(args.login):
            log.error("Utilisateur inconnu : %s", args.login)
            return 1
        else:
            log.info("%s supprimé.", args.login)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
