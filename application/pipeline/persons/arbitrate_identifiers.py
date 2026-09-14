"""Phase personnes — identifiants mal placés et conflits d'attribution d'identifiant.

Ordre-indépendant par lecture d'agrégat sur le snapshot. Le consensus des porteurs de chaque valeur d'identifiant est calculé une fois (`compute_identifier_consensus`). `requalify_misplaced_identifiers` neutralise d'abord les identifiants dont le consensus désigne une autre personne que la signature : ils sortent des porteurs, et les conflits qu'ils créaient disparaissent. `detect_identifier_conflicts` balaye ensuite le snapshot pour les valeurs qu'au moins deux personnes se disputent ; `resolve_identifier_transfers` tranche par le même consensus, transfère la valeur captée à son propriétaire légitime et remet à NULL les signatures affectées, que la cascade re-résout ensuite.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.libelles import etape
from application.pipeline.persons.requalify_identifiers import (
    compute_identifier_consensus,
    requalify_misplaced_identifiers,
)
from application.pipeline.persons.resolve_identifier_transfers import (
    detect_identifier_conflicts,
    resolve_identifier_transfers,
)
from application.ports.pipeline.persons.matching import PersonsMatchingQueries
from application.ports.repositories.person_repository import PersonRepository


def arbitrate_identifier_conflicts(
    conn: Connection,
    queries: PersonsMatchingQueries,
    logger: logging.Logger,
    *,
    person_repo: PersonRepository,
) -> dict[str, int]:
    """Neutralise les identifiants mal placés, puis tranche les conflits d'attribution d'identifiant par transfert.

    Retourne `{misplaced_identities, detached, transferred}`. Le commit est laissé au caller.
    """
    etape(logger, "Identifiants mal placés et conflits d'attribution")
    consensus = compute_identifier_consensus(conn, queries)
    requalified = requalify_misplaced_identifiers(conn, consensus, queries, logger)
    conflicts = detect_identifier_conflicts(conn, queries)
    transferred = resolve_identifier_transfers(
        conn, conflicts, consensus=consensus, queries=queries, repo=person_repo, logger=logger
    )["transferred"]

    return {
        "misplaced_identities": requalified["identities"],
        "detached": requalified["detached"],
        "transferred": transferred,
    }
