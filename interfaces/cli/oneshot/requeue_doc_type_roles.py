# STATUS: oneshot (2026-11-19)
"""Met en file de recomposition les contributions dont les rôles diffèrent du rôle imposé par le type de leur publication (`ROLE_BY_DOC_TYPE`).

La recomposition de leurs attributs leur donne ce rôle seul (`propagate_contribution_attributes_sql`). Une personne fondée seulement par ces contributions est ensuite supprimée par la purge de la phase `persons`. La phase `author_grouping` traite la file :
    run_pipeline --from author_grouping

Usage :
    uv run python -m interfaces.cli.oneshot.requeue_doc_type_roles [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from domain.contributions.contribution_roles import ROLE_BY_DOC_TYPE
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.observability.log import setup_logger

log = setup_logger("requeue_doc_type_roles", os.path.dirname(__file__))

_TARGETS = " UNION ".join(
    f"""
    SELECT g.id FROM contributions g
    JOIN publications p ON p.id = g.publication_id
    WHERE p.doc_type = '{doc_type}' AND g.roles IS DISTINCT FROM ARRAY['{role}']
    """
    for doc_type, role in ROLE_BY_DOC_TYPE.items()
)
"""Contributions d'une publication de type `ROLE_BY_DOC_TYPE`, aux rôles différents du rôle imposé."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        targets = conn.execute(text(f"SELECT count(*) FROM ({_TARGETS}) t")).scalar_one()
        log.info("%d contributions à recomposer", targets)
        if args.dry_run:
            conn.rollback()
            return
        marked = conn.execute(text(enqueue_sql(Queue.CONTRIBUTION_ATTRIBUTES, _TARGETS))).rowcount
        log.info("%d contributions marquées pour la recomposition de leurs attributs", marked)
        log.info("Ensuite : run_pipeline --from author_grouping")


if __name__ == "__main__":
    main()
