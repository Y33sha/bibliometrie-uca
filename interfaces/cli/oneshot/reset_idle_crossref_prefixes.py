# STATUS: oneshot (2026-09-24)
"""Rouvre les préfixes DOI enregistrés au nom d'un membre Crossref qui n'a déposé aucun DOI.

Crossref laisse un préfixe au nom d'un compte dormant quand une maison en ouvre un second : le préfixe garde son ancien propriétaire, pendant que le compte vivant dépose sous ce préfixe. La résolution prend alors le nom et le membre du compte mort.

Le script interroge `/members/<id>` pour chaque membre présent dans `doi_prefixes`. Les préfixes d'un membre sans dépôt repassent en attente (`publisher_id` et `publisher_checked_at` remis à NULL). La sous-étape `resolve_publishers` les reprend au run suivant, et retient cette fois le membre déposant, d'après la notice d'un DOI du préfixe.

Usage :
    python -m interfaces.cli.oneshot.reset_idle_crossref_prefixes             # applique
    python -m interfaces.cli.oneshot.reset_idle_crossref_prefixes --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.config import get_polite_pool_email
from infrastructure.sources.crossref.prefixes import member_deposits
from infrastructure.sources.polite_pool import build_user_agent

log = setup_logger("reset_idle_crossref_prefixes", os.path.dirname(__file__))

_MEMBERS = text("""
    SELECT crossref_member_id AS member, count(*) AS prefixes,
           string_agg(DISTINCT publisher_name_raw, ' ; ') AS noms
    FROM doi_prefixes
    WHERE crossref_member_id IS NOT NULL
    GROUP BY 1 ORDER BY 1
""")

_REOPEN = text("""
    UPDATE doi_prefixes SET publisher_id = NULL, publisher_checked_at = NULL
    WHERE crossref_member_id = ANY(:members)
""")

_PROGRESS = 100


def _reset(dry_run: bool) -> None:
    user_agent = build_user_agent(get_polite_pool_email())
    engine = get_sync_engine()
    with engine.connect() as conn:
        members = conn.execute(_MEMBERS).all()
    log.info("%d membres Crossref à vérifier", len(members))

    idle: list[int] = []
    unreachable = 0
    for done, row in enumerate(members, 1):
        deposits = member_deposits(row.member, user_agent=user_agent)
        if deposits is None:
            unreachable += 1
        elif deposits == 0:
            idle.append(row.member)
            log.info("Membre %d sans dépôt, %d préfixe(s) : %s", row.member, row.prefixes, row.noms)
        if done % _PROGRESS == 0:
            log.info("%d / %d membres vérifiés", done, len(members))

    log.info(
        "%d membres sans dépôt, %d injoignables%s",
        len(idle),
        unreachable,
        " (dry-run)" if dry_run else "",
    )
    if idle and not dry_run:
        with engine.begin() as conn:
            reopened = conn.execute(_REOPEN, {"members": idle}).rowcount
        log.info("%d préfixes remis en attente de résolution", reopened)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Vérifie sans écrire.")
    args = parser.parse_args()
    _reset(args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
