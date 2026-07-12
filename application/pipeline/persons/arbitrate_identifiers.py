"""Phase personnes — arbitrage des conflits d'attribution d'identifiant.

Ordre-indépendant par lecture d'agrégat sur le snapshot : `detect_identifier_conflicts` balaye le snapshot pour toutes les valeurs d'identifiant qu'au moins deux personnes se disputent ; `resolve_identifier_transfers` tranche par consensus des porteurs, transfère la valeur captée à son propriétaire légitime et remet à NULL les signatures affectées, que la cascade re-résout ensuite.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.persons.resolve_identifier_transfers import (
    detect_identifier_conflicts,
    resolve_identifier_transfers,
)
from application.ports.pipeline.persons_create import PersonsCreateQueries
from application.ports.repositories.person_repository import PersonRepository


def arbitrate_identifier_conflicts(
    conn: Connection,
    queries: PersonsCreateQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
) -> dict[str, int]:
    """Tranche les conflits d'attribution d'identifiant : transfert par consensus des porteurs, détachement des signatures captées.

    Retourne `{transferred}`. Le commit est laissé au caller.
    """
    logger.info("▶ arbitrage des conflits d'identifiant")
    conflicts = detect_identifier_conflicts(conn, queries)
    transferred = resolve_identifier_transfers(
        conn, conflicts, queries=queries, repo=person_repo, logger=logger
    )["transferred"]

    return {"transferred": transferred}
