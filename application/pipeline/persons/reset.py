"""Reset de la phase personnes : réinitialise les attributions dérivées avant le match.

Deux canaux, ordre-indépendants par lecture d'agrégat sur le snapshot :

- **Identifiant** : arbitrage frontal des conflits d'attribution. `build_identifier_conflicts` balaye le snapshot pour toutes les valeurs d'identifiant qu'au moins deux personnes se disputent ; `resolve_identifier_transfers` tranche par consensus des porteurs, transfère la valeur captée à son propriétaire légitime et remet à NULL les signatures affectées.
- **Cross-source** : recompute complet — toutes les signatures résolues en cross-source repassent à NULL, le cross-source étant un opérateur d'ensemble qu'on recalcule en bloc.

Les signatures ainsi détachées sont re-résolues par `match` puis `create` contre l'état ferme du snapshot ; le résultat ne dépend pas de l'ordre d'ingestion des sources.
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
    """Arbitre les conflits d'identifiant et remet à NULL les résolutions cross-source.

    Retourne les compteurs `{transferred, reset_cross}`. Le commit est laissé au caller.
    """
    logger.info("▶ reset : réinitialisation des rattachements dérivés")
    logger.info("  arbitrage des conflits d'identifiant...")
    conflicts = build_identifier_conflicts(conn, queries)
    transferred = resolve_identifier_transfers(
        conn, conflicts, queries=queries, repo=person_repo, logger=logger
    )["transferred"]

    logger.info("  détachement des rattachements cross-source...")
    reset_cross = queries.reset_cross_source(conn)
    logger.info("  → %d signatures détachées", reset_cross)

    return {"transferred": transferred, "reset_cross": reset_cross}
