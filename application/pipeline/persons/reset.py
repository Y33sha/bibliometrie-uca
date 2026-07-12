"""Reset de la phase personnes : arbitrage des conflits d'attribution d'identifiant.

Ordre-indépendant par lecture d'agrégat sur le snapshot : `build_identifier_conflicts` balaye le snapshot pour toutes les valeurs d'identifiant qu'au moins deux personnes se disputent ; `resolve_identifier_transfers` tranche par consensus des porteurs, transfère la valeur captée à son propriétaire légitime et remet à NULL les signatures affectées, re-résolues ensuite par `match` puis `create`.

Le cross-source n'est plus détaché en bloc ici : il est re-jugé de façon incrémentale par la cascade contre les ancres fermes, et une signature cross-source dont l'ancre a disparu est détachée en fin de phase.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.persons.resolve_identifier_transfers import (
    build_identifier_conflicts,
    resolve_identifier_transfers,
)
from application.ports.pipeline.persons_create import PersonsCreateQueries
from application.ports.repositories.person_repository import PersonRepository


def reset(
    conn: Connection,
    queries: PersonsCreateQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
) -> dict[str, int]:
    """Arbitre les conflits d'attribution d'identifiant (transfert par consensus, détachement des signatures captées).

    Retourne `{transferred}`. Le commit est laissé au caller.
    """
    logger.info("▶ reset : arbitrage des conflits d'identifiant")
    conflicts = build_identifier_conflicts(conn, queries)
    transferred = resolve_identifier_transfers(
        conn, conflicts, queries=queries, repo=person_repo, logger=logger
    )["transferred"]

    return {"transferred": transferred}
